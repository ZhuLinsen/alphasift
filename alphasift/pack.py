"""Build, verify, and use the offline CN daily bar pack."""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import socket
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter

from alphasift.config import Config
from alphasift.daily import _BAOSTOCK_LOCK, _to_baostock_code, _to_tencent_code, fetch_daily_history
from alphasift.markets import get_market, latest_settled_close
from alphasift.snapshot import fetch_cn_snapshot, fetch_snapshot_with_fallback
from alphasift.jsonutil import dumps_strict_json

DEFAULT_DAYS = 250
DEFAULT_TAG = "data-cn"
DEFAULT_REPO = ""
FIELDS = ("open", "high", "low", "close", "pre_close", "volume", "amount")
PRICE_FIELDS = FIELDS[:5]
META_FIELDS = ("name", "industry", "pe_ratio", "pb_ratio", "total_mv", "circ_mv", "list_date", "is_st")
_ASSETS = ("daily.npz", "meta.csv.gz")
_MANIFEST = "manifest.json"
_SCHEMA_VERSION = 1
_MIN_COVERAGE = 0.8
_TICKPLUS_FIELDS = dict(zip(("o", "h", "l", "c", "pc", "v", "a"), FIELDS))
_BAOSTOCK_FIELDS = ("date", "open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus")
_CODE_PATTERN = re.compile(r"(?:(?:sh|sz|bj)\.?)?([0-9]{1,6})(?:\.(?:sh|ss|sz|bj)|\.0)?", re.I)
_A_SHARE = ("600", "601", "603", "605", "688", "689", "000", "001", "002", "003", "300", "301", "4", "8", "920")
_CN_TZ = ZoneInfo(get_market("cn").timezone)
# Raw quote columns the existing CN snapshot sources keep next to the normalized ones:
# source -> (open, high, low, previous close, volume, shares per volume unit).
_SNAPSHOT_QUOTES = {
    "sina": ("open", "high", "low", "settlement", "volume", 1),
    "efinance": ("今开", "最高", "最低", "昨日收盘", "成交量", 100),
    "akshare_em": ("今开", "最高", "最低", "昨收", "成交量", 100),
    "em_datacenter": ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "PRE_CLOSE_PRICE", "VOLUME", 100),
}
_REFERENCE_CODES = ("000001", "600519", "601398")
_MAX_FAILED_CODES = 0.05
_PACK_THREAD_LOCK = threading.Lock()
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_TENCENT_HEADERS = {"User-Agent": "Mozilla/5.0"}
_YFINANCE_BATCH_SIZE = 100
_YFINANCE_CHUNK_DELAY_SEC = 0.25
logger = logging.getLogger(__name__)


def _tencent_volume_multiplier(code: str) -> int:
    """STAR (688) and CDR (689) report Tencent volume in shares; others use lots."""
    return 1 if code.startswith(("688", "689")) else 100


def _tencent_session(workers: int = 2) -> requests.Session:
    session = requests.Session()
    pool = max(4, int(workers))
    adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class PackError(ValueError):
    """The pack or its input did not pass validation."""


class SnapshotStitchError(PackError):
    """The error text can be surfaced as a snapshot degradation note."""


@dataclass
class DailyPack:
    dates: np.ndarray
    codes: np.ndarray
    matrices: dict[str, np.ndarray]
    meta: pd.DataFrame
    sources: tuple[str, ...] = ()
    manifest: dict = field(default_factory=dict)

    @property
    def trade_date(self) -> str:
        return str(self.dates[-1])

    def history(self, code: str, *, include_missing: bool = False) -> pd.DataFrame:
        """Return one code's raw bars, dropping missing sessions by default."""
        code = _code(code)
        index = self.codes.searchsorted(code)
        if index == len(self.codes) or self.codes[index] != code:
            raise KeyError(code)
        frame = pd.DataFrame({"date": self.dates, **{key: self.matrices[key][:, index] for key in FIELDS}})
        return frame if include_missing else frame.dropna(subset=["close"]).reset_index(drop=True)


class IncrementalProvider(Protocol):
    name: str

    def fetch_day(self, trade_date: str) -> pd.DataFrame:
        """Return raw CN bars for one session, with code and all FIELDS (volume in shares)."""
        ...


class TickPlusProvider:
    """Optional TickPlus updatedaykline source, used only when TICKPLUS_API_KEY is set.

    Covers about a week. Not live-verified: fixture coverage follows the
    documented fields and the API's list format. The documented endpoint uses
    HTTP and places the key in the query string.
    """

    name = "tickplus"

    def fetch_day(self, trade_date: str) -> pd.DataFrame:
        day = _iso_date(trade_date)
        token = os.getenv("TICKPLUS_API_KEY", "").strip()
        if not token:
            raise PackError("TickPlus requires TICKPLUS_API_KEY")
        if day < (datetime.now(_CN_TZ).date() - timedelta(days=7)).isoformat():
            raise PackError("TickPlus updatedaykline only covers roughly the last week")
        query = urlencode({"symbol": "stock", "dividend": "1", "tradeDate": day, "token": token})
        # http.client has request tracing off by default. Avoid HTTP adapters
        # whose DEBUG logs include request targets, and never follow redirects.
        conn = http.client.HTTPConnection("api.tickplus.org", timeout=30)
        try:
            conn.request("GET", "/plus/basic/updatedaykline?" + query)
            response = conn.getresponse()
            status = response.status
            body = response.read() if status == 200 else b""
        except (OSError, http.client.HTTPException, ValueError):
            raise PackError("TickPlus updatedaykline request failed") from None
        finally:
            conn.close()
        if status != 200:
            raise PackError(f"TickPlus updatedaykline HTTP status {status}")
        try:
            payload = json.loads(body)
        except ValueError:
            raise PackError("TickPlus updatedaykline returned invalid JSON") from None
        return _parse_tickplus_day(payload, day)


class SnapshotProvider:
    """Today's full-market bars from the project's existing CN snapshot sources.

    Only valid for the latest settled session: a snapshot has no history, so
    an older date is left to the daily-history gap fill.
    """

    name = "snapshot"

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    def fetch_day(self, trade_date: str) -> pd.DataFrame:
        day = _iso_date(trade_date)
        if day != expected_trade_date():
            raise PackError("A snapshot only covers the latest settled session")
        config = self._config or Config.from_env()
        for source in config.snapshot_source_priority:
            if source not in _SNAPSHOT_QUOTES:
                continue
            try:
                snapshot = fetch_cn_snapshot(source)
                if snapshot.attrs.get("quote_date") not in (None, day):
                    raise PackError("Snapshot quote date does not match the requested date")
                bars = _normalize_day(_snapshot_bars(snapshot))
            except Exception as exc:
                logger.warning("Snapshot source %s cannot supply daily bars: %s", source, exc)
                continue
            self.name = f"snapshot:{source}"
            return bars
        raise PackError("No snapshot source supplied open/high/low/previous close")


class TencentQuoteProvider:
    """Today's full-market bars from Tencent batch quotes (qt.gtimg.cn)."""

    name = "tencent_quote"

    def __init__(
        self,
        codes: Sequence[str] | None = None,
        *,
        config: Config | None = None,
        batch_size: int = 80,
        workers: int = 2,
        batch_delay_sec: float = 0.15,
    ) -> None:
        self._codes = list(dict.fromkeys(_code(c) for c in codes)) if codes else []
        self._config = config
        self._batch_size = max(1, int(batch_size))
        self._workers = max(1, int(workers))
        self._batch_delay_sec = max(0.0, float(batch_delay_sec))

    def fetch_day(self, trade_date: str) -> pd.DataFrame:
        day = _iso_date(trade_date)
        codes = list(self._codes)
        if not codes:
            snapshot = _latest_snapshot(self._config or Config.from_env())
            codes = sorted({c for c in snapshot["code"].map(_code) if c.startswith(_A_SHARE)})
        if not codes:
            raise PackError("No A-share codes available for Tencent batch quotes")
        chunks = [codes[i:i + self._batch_size] for i in range(0, len(codes), self._batch_size)]
        local_state = threading.local()
        created_sessions: list[requests.Session] = []
        sessions_lock = threading.Lock()

        def fetch_chunk(idx_chunk: tuple[int, list[str]]) -> list[dict[str, object]]:
            idx, chunk = idx_chunk
            if idx > 0 and self._batch_delay_sec > 0:
                time.sleep(self._batch_delay_sec)
            session = getattr(local_state, "session", None)
            if session is None:
                session = _tencent_session(self._workers)
                local_state.session = session
                with sessions_lock:
                    created_sessions.append(session)
            symbols = ",".join(_to_tencent_code(c) for c in chunk)
            resp = session.get(f"{_TENCENT_QUOTE_URL}{symbols}", headers=_TENCENT_HEADERS, timeout=10)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
            return _parse_tencent_quote_lines(text, day)

        rows: list[dict[str, object]] = []
        indexed_chunks = list(enumerate(chunks))
        try:
            if self._workers <= 1 or len(chunks) <= 1:
                for item in indexed_chunks:
                    rows.extend(fetch_chunk(item))
            else:
                with ThreadPoolExecutor(max_workers=min(self._workers, len(chunks))) as pool:
                    for chunk_rows in pool.map(fetch_chunk, indexed_chunks):
                        rows.extend(chunk_rows)
        finally:
            for sess in created_sessions:
                sess.close()
        if not rows:
            raise PackError(f"Tencent batch quotes returned no bars for {day}")
        frame = pd.DataFrame(rows, columns=["code", *FIELDS]).drop_duplicates("code", keep="last")
        return _normalize_day(frame).reset_index(drop=True)


def _parse_tencent_quote_lines(text: str, trade_date: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if "=\"" not in line:
            continue
        body = line.split("=\"", 1)[1].rsplit("\";", 1)[0]
        parts = body.split("~")
        if len(parts) <= 37:
            continue
        raw_code = parts[2].strip()
        if not raw_code:
            continue
        try:
            code = _code(raw_code)
        except PackError:
            continue
        digits = "".join(ch for ch in parts[30] if ch.isdigit())
        if len(digits) < 8:
            continue
        quote_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        if quote_date != trade_date:
            continue
        try:
            close_v = float(parts[3])
            pre_close_v = float(parts[4])
            open_v = float(parts[5])
            high_v = float(parts[33])
            low_v = float(parts[34])
            vol_v = float(parts[6])
            amt_wan = float(parts[37]) if parts[37].strip() else 0.0
        except ValueError:
            continue
        if not all(np.isfinite(v) for v in (close_v, pre_close_v, open_v, high_v, low_v, vol_v, amt_wan)):
            continue
        if open_v <= 0 or close_v <= 0 or high_v <= 0 or low_v <= 0 or pre_close_v <= 0 or vol_v <= 0 or amt_wan < 0:
            continue
        rows.append({
            "code": code,
            "open": open_v,
            "high": high_v,
            "low": low_v,
            "close": close_v,
            "pre_close": pre_close_v,
            "volume": vol_v * _tencent_volume_multiplier(code),
            "amount": amt_wan * 10000.0,
        })
    return rows


def _snapshot_bars(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Map a snapshot's raw quote columns onto the pack fields; drop untraded rows."""
    frame = snapshot.copy()
    if "close" not in frame.columns and "price" in frame.columns:
        frame = frame.rename(columns={"price": "close"})
    quotes = _SNAPSHOT_QUOTES.get(str(snapshot.attrs.get("snapshot_source", "")))
    if quotes and "pre_close" not in frame.columns:
        *names, lot = quotes
        if all(name in frame.columns for name in names):
            for key, name in zip(("open", "high", "low", "pre_close", "volume"), names):
                frame[key] = pd.to_numeric(frame[name], errors="coerce")
            frame["volume"] *= lot
    if {"open", "volume"} <= set(frame.columns):
        traded = pd.to_numeric(frame["open"], errors="coerce").gt(0) & pd.to_numeric(frame["volume"], errors="coerce").gt(0)
        frame = frame.loc[traded]
    return frame


def _parse_tickplus_day(payload: object, trade_date: str) -> pd.DataFrame:
    expected = {"t", "code", *_TICKPLUS_FIELDS}
    if not isinstance(payload, list) or not payload or any(
        not isinstance(row, dict) or not expected <= row.keys() for row in payload
    ):
        raise PackError("TickPlus updatedaykline returned invalid or empty bar data")
    # Select only documented fields. Ignore any vendor messages or other extras.
    frame = pd.DataFrame.from_records(payload, columns=["t", "code", *_TICKPLUS_FIELDS])
    if not frame["t"].astype("string").str.slice(0, 10).eq(trade_date).fillna(False).all():
        raise PackError("TickPlus updatedaykline returned bars for a different trade date")
    frame = frame.drop(columns="t").rename(columns=_TICKPLUS_FIELDS)
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") * 100
    # Suspensions can be omitted or carried as zero-volume rows by a feed.
    bars = _normalize_day(frame.loc[frame["volume"] != 0])
    if bars.empty:
        raise PackError("TickPlus updatedaykline returned no trading bars")
    return bars.reset_index(drop=True)


def pack_dir(config: Config | None = None) -> Path:
    """Resolve the pack directory from config override, environment, or AlphaSift's data dir."""
    if config is not None and config.daily_pack_dir is not None:
        return Path(config.daily_pack_dir).expanduser()
    override = os.getenv("ALPHASIFT_PACK_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    resolved = config or Config.from_env()
    if resolved.daily_pack_dir is not None:
        return Path(resolved.daily_pack_dir).expanduser()
    return resolved.data_dir / "pack" / "cn"


def expected_trade_date(now: datetime | None = None) -> str:
    """Estimate the latest settled CN session using weekdays; use an explicit date on holidays."""
    local = (now or datetime.now(_CN_TZ)).astimezone(_CN_TZ)
    settled = latest_settled_close("cn", local)
    if settled:
        return settled[0].isoformat()
    day = local.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def is_fresh(pack: DailyPack, expected: str | date) -> bool:
    """Return whether the pack ends on the expected CN trade date."""
    return pack.trade_date == _iso_date(expected)


def load_pack(directory: str | Path | None = None) -> DailyPack:
    """Verify and load the CN pack, including both assets' SHA-256 hashes."""
    path = Path(directory) if directory is not None else pack_dir()
    with _pack_lock(path):
        return _load_pack(path)


def _load_pack(path: Path) -> DailyPack:
    manifest = _read_manifest(path)
    for name in _ASSETS:
        _verify_asset(path / name, manifest["files"][name])
    with np.load(path / "daily.npz", allow_pickle=False) as archive:
        dates, codes = archive["dates"], archive["codes"]
        matrices = {key: archive[key] for key in FIELDS}
    meta = pd.read_csv(
        path / "meta.csv.gz", dtype={"code": str, "name": str, "industry": str, "list_date": str, "is_st": "boolean"},
    )
    pack = DailyPack(dates, codes, matrices, meta, tuple(manifest["sources"]), manifest)
    _check_structure(pack)
    if any(manifest.get(key) != value for key, value in _pack_dimensions(pack).items()):
        raise PackError("Pack manifest dates or dimensions do not match daily.npz")
    return pack


def save_pack(directory: str | Path, pack: DailyPack) -> dict:
    """Validate, then publish a pack and return its new manifest."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    with _pack_lock(path, write=True):
        return _save_pack(path, pack)


def _save_pack(path: Path, pack: DailyPack) -> dict:
    _check_structure(pack)
    _check_coverage(pack.dates, pack.matrices["close"])
    with TemporaryDirectory(prefix=".pack-", dir=path) as tmp:
        stage = Path(tmp)
        np.savez_compressed(stage / "daily.npz", dates=pack.dates, codes=pack.codes, **pack.matrices)
        pack.meta.to_csv(stage / "meta.csv.gz", index=False, compression="gzip")
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "market": "cn",
            **_pack_dimensions(pack),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "sources": list(pack.sources),
            "files": {name: _asset_info(stage / name) for name in _ASSETS},
        }
        (stage / _MANIFEST).write_text(dumps_strict_json(manifest, indent=2) + "\n", encoding="utf-8")
        _publish(stage, path)
    return manifest


def forward_adjust(pack: DailyPack, *, rtol: float = 1e-5) -> dict[str, np.ndarray]:
    """Return qfq matrices anchored to the last available bar of each code.

    Scale each price field, including pre_close, by factors after its row.
    Volume (shares) and amount (yuan) stay in original units, as in daily.py's
    qfq adjustment. The returned mapping shares those two raw arrays.
    """
    close = pack.matrices["close"]
    pre_close = pack.matrices["pre_close"]
    valid = np.isfinite(close) & (close > 0)
    rows = np.arange(len(close), dtype=np.intp)[:, None]
    last = np.maximum.accumulate(np.where(valid, rows, -1), axis=0)
    previous = np.take_along_axis(close, last[:-1].clip(min=0), axis=0)
    reference = pre_close[1:]
    event = valid[1:] & (last[:-1] >= 0) & np.isfinite(reference) & (reference > 0)
    event &= ~np.isclose(reference, previous, rtol=rtol, atol=0)
    factors = np.ones(close.shape, dtype=np.float64)
    np.divide(reference, previous, out=factors[:-1], where=event, dtype=np.float64)
    scales = np.cumprod(factors[::-1], axis=0)[::-1]
    return {
        **pack.matrices,
        **{key: (pack.matrices[key] * scales).astype(np.float32) for key in PRICE_FIELDS},
    }


def pack_price_paths(
    pack: DailyPack,
    codes: Sequence[str] | None = None,
    *,
    adjusted: bool = True,
    include_raw: bool = True,
) -> dict[str, pd.DataFrame]:
    """Extract per-code OHLCV price path DataFrames from ``pack`` for evaluation.

    When ``include_raw=True``, also attaches unadjusted ``raw_open``, ``raw_high``,
    ``raw_low``, ``raw_close`` and ``raw_pre_close`` (rounded to 4 decimals to
    remove float32 storage drift) so CN price-limit checks evaluate exact raw quotes.
    """
    mats = forward_adjust(pack) if adjusted else pack.matrices
    if codes is None:
        target_codes = [str(c) for c in pack.codes]
    else:
        seen: set[str] = set()
        target_codes = []
        for raw in codes:
            try:
                norm = _code(raw)
            except PackError:
                continue
            if norm not in seen:
                seen.add(norm)
                target_codes.append(norm)

    dates = pack.dates
    out: dict[str, pd.DataFrame] = {}
    for code in target_codes:
        idx = int(pack.codes.searchsorted(code))
        if idx >= len(pack.codes) or pack.codes[idx] != code:
            continue
        data: dict[str, Any] = {
            "date": dates,
            **{key: mats[key][:, idx].astype(np.float64) for key in FIELDS},
        }
        if include_raw:
            for key in PRICE_FIELDS:
                data[f"raw_{key}"] = np.round(pack.matrices[key][:, idx].astype(np.float64), 4)
        frame = pd.DataFrame(data)
        valid = frame["close"].notna() & (frame["close"] > 0)
        frame = frame.loc[valid].reset_index(drop=True)
        if not frame.empty:
            frame.attrs["daily_source"] = "daily_pack"
            out[code] = frame
    return out


def stitch_snapshot(pack: DailyPack, snapshot: pd.DataFrame, trade_date: str | date | None = None) -> DailyPack:
    """Return an in-memory pack with a provisional snapshot row appended.

    Requires code, open, high, low, close (or price), pre_close, volume in
    shares, and amount in yuan. Snapshots from sina, efinance, akshare_em and
    em_datacenter carry these under their own column names and are mapped
    automatically; tushare snapshots do not. SnapshotStitchError gives a
    degradation note.
    """
    day = _iso_date(trade_date or datetime.now(_CN_TZ).date())
    if day <= pack.trade_date:
        return pack
    if snapshot.attrs.get("quote_date") not in (None, day):
        raise SnapshotStitchError("Snapshot stitch skipped: quote date does not match the requested date")
    try:
        bars = _normalize_day(_snapshot_bars(snapshot))
        meta = _snapshot_meta(snapshot)
        row = _from_day(day, bars, meta, _snapshot_source(snapshot))
        return _append(pack, row, meta)
    except PackError as exc:
        raise SnapshotStitchError(f"Snapshot stitch skipped: {exc}") from None


def pull(directory: str | Path | None = None, *, repo: str | None = None, tag: str = DEFAULT_TAG) -> dict:
    """Fetch the manifest and publish verified GitHub assets if hashes changed."""
    path = Path(directory) if directory is not None else pack_dir()
    repo = (repo or os.getenv("ALPHASIFT_PACK_REPO", "") or DEFAULT_REPO).strip()
    if not repo:
        raise PackError(
            "CN daily pack is private and not publicly distributed; build locally with "
            "'alphasift pack build' / 'python scripts/build_pack.py backfill' or set ALPHASIFT_PACK_REPO"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
        raise PackError("Invalid GitHub pack repository or release tag")
    base = f"https://github.com/{repo}/releases/download/{tag}"
    path.mkdir(parents=True, exist_ok=True)
    with _pack_lock(path, write=True), TemporaryDirectory(prefix=".pack-", dir=path) as tmp:
        stage = Path(tmp)
        _download(base, stage / _MANIFEST)
        remote = _read_manifest(stage)
        try:
            local = _read_manifest(path)
            if all(local["files"][key]["sha256"] == remote["files"][key]["sha256"] for key in _ASSETS):
                for key in _ASSETS:
                    _verify_asset(path / key, local["files"][key])
                return local
        except (FileNotFoundError, PackError):
            pass
        for key in _ASSETS:
            _download(base, stage / key)
        _load_pack(stage)
        _publish(stage, path)
    return remote


def pull_with_wait(
    directory: str | Path | None = None,
    *,
    repo: str | None = None,
    tag: str = DEFAULT_TAG,
    expected_trade_date: str | date | None = None,
    max_wait_sec: float = 0.0,
    poll_interval_sec: float = 30.0,
    sleep_fn=time.sleep,
) -> dict:
    """Pull a private ``data-cn`` release pack when ``ALPHASIFT_PACK_REPO`` is configured, optionally polling until ``expected_trade_date`` arrives."""
    target = _iso_date(expected_trade_date) if expected_trade_date is not None else expected_trade_date_str()
    budget = max(0.0, float(max_wait_sec))
    interval = max(0.1, float(poll_interval_sec))
    waited = 0.0
    attempts = 0
    last_manifest: dict | None = None
    last_error: Exception | None = None

    while True:
        attempts += 1
        try:
            manifest = pull(directory, repo=repo, tag=tag)
            last_manifest = manifest
            if target is None or str(manifest.get("trade_date", "")) >= target:
                return {
                    **manifest,
                    "expected_trade_date": target,
                    "fresh": True if target is None else str(manifest.get("trade_date", "")) >= target,
                    "attempts": attempts,
                    "waited_sec": round(waited, 2),
                }
        except (OSError, PackError) as exc:
            last_error = exc

        if waited >= budget:
            if last_manifest is not None:
                return {
                    **last_manifest,
                    "expected_trade_date": target,
                    "fresh": False if target is not None else True,
                    "attempts": attempts,
                    "waited_sec": round(waited, 2),
                }
            if last_error is not None:
                raise last_error
            raise PackError("Pack pull failed without manifest")

        step = min(interval, budget - waited)
        if step > 0:
            sleep_fn(step)
            waited += step


def expected_trade_date_str() -> str:
    return expected_trade_date()


def _download(base: str, dst: Path) -> None:
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    kwargs: dict[str, Any] = {"headers": {"Authorization": f"Bearer {token}"}} if token else {}
    try:
        with requests.get(f"{base}/{dst.name}", stream=True, timeout=(10, 60), **kwargs) as response:
            response.raise_for_status()
            with dst.open("wb") as out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    out.write(chunk)
    except requests.RequestException:
        raise PackError(f"GitHub pack download failed for {dst.name}") from None


def _read_manifest(path: Path) -> dict:
    try:
        manifest = json.loads((path / _MANIFEST).read_text(encoding="utf-8"))
    except ValueError:
        raise PackError("Invalid pack manifest JSON") from None
    if not isinstance(manifest, dict) or manifest.get("market") != "cn" or manifest.get("schema_version") != _SCHEMA_VERSION:
        raise PackError("Unsupported CN pack manifest schema")
    files, sources = manifest.get("files"), manifest.get("sources")
    if not isinstance(files, dict) or not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
        raise PackError("Pack manifest is missing valid files or sources")
    first, last = _iso_date(manifest.get("first_date")), _iso_date(manifest.get("trade_date"))
    if first > last or any(type(manifest.get(key)) is not int or manifest[key] < 1 for key in ("n_dates", "n_codes")):
        raise PackError("Pack manifest is missing valid dates or dimensions")
    for key in _ASSETS:
        asset = files.get(key)
        if (not isinstance(asset, dict) or type(asset.get("size")) is not int or asset["size"] < 0
                or not isinstance(asset.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
            raise PackError(f"Invalid pack manifest asset entry for {key}")
    return manifest


def _asset_info(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}


def _verify_asset(path: Path, expected: dict) -> None:
    actual = _asset_info(path)
    if actual["sha256"] != expected["sha256"]:
        raise PackError(f"Pack SHA-256 mismatch for {path.name}")
    if actual["size"] != expected["size"]:
        raise PackError(f"Pack size mismatch for {path.name}")


@contextmanager
def _pack_lock(path: Path, *, write: bool = False) -> Iterator[None]:
    if os.name != "posix":
        with _PACK_THREAD_LOCK:
            yield
        return
    import fcntl

    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)


def _publish(stage: Path, path: Path) -> None:
    # Publish the manifest last and restore the previous files if a rename fails.
    names = (*_ASSETS, _MANIFEST)
    for name in names:
        if (path / name).exists():
            os.link(path / name, stage / (name + ".prev"))
    replaced = []
    try:
        for name in names:
            (stage / name).replace(path / name)
            replaced.append(name)
    except (OSError, KeyboardInterrupt):
        for name in reversed(replaced):
            backup = stage / (name + ".prev")
            if backup.exists():
                backup.replace(path / name)
            else:
                (path / name).unlink()
        raise


def _pack_dimensions(pack: DailyPack) -> dict:
    return {"first_date": str(pack.dates[0]), "trade_date": pack.trade_date,
            "n_dates": len(pack.dates), "n_codes": len(pack.codes)}


def _check_structure(pack: DailyPack) -> None:
    if pack.dates.ndim != 1 or pack.dates.dtype.kind != "U" or not len(pack.dates):
        raise PackError("Pack dates must be a nonempty ISO date vector")
    _check_dates(pack.dates)
    if (pack.codes.ndim != 1 or pack.codes.dtype.kind != "U" or not len(pack.codes)
            or not all(re.fullmatch(r"[0-9]{6}", code) for code in pack.codes)
            or np.any(pack.codes[1:] <= pack.codes[:-1])):
        raise PackError("Pack codes must be six digits, unique and sorted")
    shape = (len(pack.dates), len(pack.codes))
    if set(pack.matrices) != set(FIELDS) or any(
        arr.shape != shape or arr.dtype != np.float32 for arr in pack.matrices.values()
    ):
        raise PackError("Pack fields must all be float32 date-by-code matrices")
    if ("code" not in pack.meta or pack.meta["code"].duplicated().any()
            or set(pack.meta["code"]) != set(pack.codes)):
        raise PackError("Pack metadata must include one row per code")


def _check_dates(dates: Sequence[str] | np.ndarray) -> None:
    for value in dates:
        _iso_date(value)
    if any(right <= left for left, right in zip(dates, dates[1:])):
        raise PackError("Pack dates must be strictly increasing with no duplicates")


class _CoverageError(PackError):
    def __init__(self, dates: Sequence[str] | np.ndarray, counts: np.ndarray, bad: np.ndarray, previous: int):
        self.bad = bad
        index = int(np.flatnonzero(bad)[0])
        prior = counts[index - 1] if index else previous
        comparison = f", previous day {prior}" if prior else ""
        super().__init__(f"Truncated daily bar coverage on {dates[index]} ({counts[index]} bars{comparison})")


def _check_coverage(dates: Sequence[str] | np.ndarray, close: np.ndarray, *, previous: int = 0) -> None:
    counts = np.count_nonzero(np.isfinite(close), axis=1)
    bad = (counts == 0) | (counts < np.r_[previous, counts[:-1]] * _MIN_COVERAGE)
    if bad.any():
        raise _CoverageError(dates, counts, bad, previous)


def _iso_date(value: object) -> str:
    try:
        text = str(value)
        if date.fromisoformat(text).isoformat() == text:
            return text
    except ValueError:
        pass
    raise PackError("Expected a trade date in YYYY-MM-DD format")


def _code(value: object) -> str:
    match = _CODE_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise PackError("Invalid CN stock code")
    return match[1].zfill(6)


def _normalize_day(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["code", *FIELDS]
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise PackError(f"Missing required bar columns: {', '.join(missing)}")
    bars = frame[columns].copy()
    bars["code"] = bars["code"].map(_code)
    if bars["code"].duplicated().any():
        raise PackError("Duplicate code in daily bars")
    bars[list(FIELDS)] = _numeric_bars(bars)
    return bars.dropna(subset=["close"])


def _numeric_bars(frame: pd.DataFrame) -> pd.DataFrame:
    values = frame[list(FIELDS)].apply(pd.to_numeric, errors="coerce").astype(np.float32)
    values = values.loc[~values.isna().all(axis=1)]
    # Amount may be unknown: the free daily K-line sources do not report it.
    if (not np.isfinite(values.drop(columns="amount").to_numpy()).all() or np.isinf(values["amount"]).any()
            or (values[list(PRICE_FIELDS[:4])] <= 0).any().any()
            or (values[["pre_close", "volume", "amount"]] < 0).any().any()):
        raise PackError("Daily bar has missing or invalid numeric fields")
    return values


def _snapshot_meta(snapshot: pd.DataFrame) -> pd.DataFrame:
    meta = snapshot[["code", *(key for key in META_FIELDS if key in snapshot)]].copy()
    meta["code"] = meta["code"].map(_code)
    if "is_st" in meta:
        flag = meta["is_st"].astype("string").str.strip().str.lower()
        meta["is_st"] = flag.map({"true": True, "false": False, "1": True, "0": False}).astype("boolean")
    elif "name" in meta:
        meta["is_st"] = meta["name"].astype("string").str.strip().str.contains(r"^S?\*?ST", case=False)
    return meta.drop_duplicates("code").set_index("code")


def _snapshot_source(snapshot: pd.DataFrame) -> str:
    return f"snapshot:{snapshot.attrs.get('snapshot_source', 'provided')}"


def _empty_matrices(n_dates: int, n_codes: int) -> dict[str, np.ndarray]:
    return {key: np.full((n_dates, n_codes), np.nan, dtype=np.float32) for key in FIELDS}


def _from_day(day: str, bars: pd.DataFrame, meta: pd.DataFrame, source: str) -> DailyPack:
    ordered = bars.sort_values("code")
    codes = ordered["code"].to_numpy(dtype="U6")
    matrices = {key: ordered[key].to_numpy(dtype=np.float32)[None, :] for key in FIELDS}
    return DailyPack(np.array([day]), codes, matrices, meta.reindex(codes).reset_index(), (source,))


def _append(pack: DailyPack, newer: DailyPack, meta: pd.DataFrame, *, days: int | None = None) -> DailyPack:
    dates = np.concatenate([pack.dates, newer.dates])
    _check_dates(dates)
    codes = np.union1d(pack.codes, newer.codes)
    matrices = _empty_matrices(len(dates), len(codes))
    left, right = codes.searchsorted(pack.codes), codes.searchsorted(newer.codes)
    for key, values in matrices.items():
        values[:len(pack.dates), left] = pack.matrices[key]
        values[len(pack.dates):, right] = newer.matrices[key]
    _check_coverage(dates, matrices["close"])
    if days is not None:
        dates = dates[-days:]
        matrices = {key: values[-days:] for key, values in matrices.items()}
        keep = np.isfinite(matrices["close"]).any(axis=0) | np.isin(codes, meta.index)
        codes = codes[keep]
        matrices = {key: values[:, keep] for key, values in matrices.items()}
    meta = meta.reindex(codes).reset_index()
    sources = tuple(dict.fromkeys((*pack.sources, *newer.sources)))
    return DailyPack(dates, codes, matrices, meta, sources)


@contextmanager
def _baostock_session() -> Iterator:
    import baostock as bs

    # The SDK has one process-global socket, shared with the existing daily path.
    with _BAOSTOCK_LOCK:
        prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(15.0)
        try:
            login = bs.login()
            _check_baostock(login)
            try:
                yield bs
            finally:
                try:
                    bs.logout()
                except Exception:
                    logger.warning("Baostock logout failed")
        finally:
            socket.setdefaulttimeout(prev_timeout)


def _baostock_reachable() -> bool:
    if os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true":
        return False
    try:
        import baostock.common.contants as constants

        with socket.create_connection((constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT), timeout=5):
            return True
    except Exception:
        return False


@contextmanager
def _history_session(source: str = "auto") -> Iterator[tuple[object | None, str]]:
    """Yield ``(baostock_session_or_none, mode)`` where mode is baostock, yfinance or daily."""
    if source not in ("auto", "baostock", "yfinance", "daily"):
        raise PackError("history source must be auto, baostock, yfinance or daily")
    if source == "daily":
        logger.info("Using daily (sina+tencent) history source")
        yield None, "daily"
        return
    if source == "yfinance":
        logger.info("Using yfinance history source")
        yield None, "yfinance"
        return
    if source == "auto" and not _baostock_reachable():
        logger.info("Using batched yfinance daily history (baostock skipped or unreachable)")
        yield None, "yfinance"
        return
    logger.info("Using baostock history source")
    with _baostock_session() as bs:
        yield bs, "baostock"


def _source_frame(code: str, count: int, source: str) -> pd.DataFrame:
    frame = fetch_daily_history(code, lookback_days=count, source=source, cache_write=False)
    frame = frame.assign(date=pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d"))
    return frame.drop_duplicates("date").set_index("date").sort_index()


def _is_bse_code(code: str) -> bool:
    return _code(code).startswith(("4", "8", "920"))


def _to_yahoo_cn_symbol(code: str) -> str | None:
    normalized = _code(code)
    if _is_bse_code(normalized):
        return None
    if normalized.startswith(("6", "9", "5")):
        return f"{normalized}.SS"
    if normalized.startswith(("0", "3")):
        return f"{normalized}.SZ"
    return None


def _yf_download(
    tickers: str | list[str],
    *,
    start: str,
    end: str,
    actions: bool = True,
) -> pd.DataFrame:
    import yfinance as yf

    return yf.download(
        tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        actions=actions,
        group_by="ticker",
        progress=False,
        threads=True,
    )


def _extract_yf_frame(raw: pd.DataFrame, symbol: str, *, single: bool) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return pd.DataFrame()
        return raw[symbol].copy()
    return raw.copy() if single else pd.DataFrame()


def _session_dates(bs, start: str, end: str, *, mode: str = "daily") -> list[str]:
    if bs is not None:
        return _baostock_dates(bs, start, end)
    days: set[str] = set()
    if mode == "yfinance":
        end_pad = (date.fromisoformat(end) + timedelta(days=3)).isoformat()
        symbols = [sym for code in _REFERENCE_CODES if (sym := _to_yahoo_cn_symbol(code)) is not None]
        try:
            raw = _yf_download(symbols, start=start, end=end_pad, actions=False)
            for sym in symbols:
                sub = _extract_yf_frame(raw, sym, single=len(symbols) == 1)
                if sub.empty or "Close" not in sub.columns:
                    continue
                valid = sub.dropna(subset=["Close"])
                if not valid.empty:
                    idx = pd.to_datetime(valid.index, errors="coerce")
                    days.update(idx[~idx.isna()].strftime("%Y-%m-%d").tolist())
        except Exception as exc:
            logger.warning("Yahoo trading calendar reference failed: %s", exc)
    if not days:
        count = max((datetime.now(_CN_TZ).date() - date.fromisoformat(start)).days + 20, 30)
        for code in _REFERENCE_CODES:
            try:
                days.update(_source_frame(code, count, "sina").index)
            except Exception as exc:
                logger.warning("Trading calendar reference %s failed: %s", code, exc)
    dates = sorted(day for day in days if start <= day <= end)
    if not dates and not days:
        raise PackError("No daily source returned a trading calendar")
    return dates


def _yfinance_bars_from_frame(frame: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    """Convert a yfinance auto_adjust=False, actions=True DataFrame to unadjusted pack bars."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", *FIELDS])
    required_ohlcv = ("Open", "High", "Low", "Close", "Volume")
    if any(col not in frame.columns for col in required_ohlcv):
        return pd.DataFrame(columns=["date", *FIELDS])

    sub = frame.copy()
    idx = pd.to_datetime(sub.index, errors="coerce")
    sub = sub.loc[~idx.isna()].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", *FIELDS])
    sub.index = idx[~idx.isna()].strftime("%Y-%m-%d")
    sub = sub[~sub.index.duplicated(keep="last")].sort_index()
    sub = sub.loc[sub.index <= dates[-1]]
    if sub.empty:
        return pd.DataFrame(columns=["date", *FIELDS])

    for col in (*required_ohlcv, "Adj Close", "Dividends", "Stock Splits"):
        if col in sub.columns:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")

    valid_close = np.isfinite(sub["Close"]) & sub["Close"].gt(0)
    sub = sub.loc[valid_close].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", *FIELDS])

    splits = sub["Stock Splits"].fillna(0.0) if "Stock Splits" in sub.columns else pd.Series(0.0, index=sub.index)
    factors = splits.where(splits > 0, 1.0).to_numpy(dtype=np.float64)
    cum_split = np.cumprod(factors[::-1])[::-1]
    future_split = np.ones_like(cum_split)
    if len(cum_split) > 1:
        future_split[:-1] = cum_split[1:]
    sub["_cum_split"] = future_split

    traded = (
        np.isfinite(sub["Open"]) & sub["Open"].gt(0)
        & np.isfinite(sub["High"]) & sub["High"].gt(0)
        & np.isfinite(sub["Low"]) & sub["Low"].gt(0)
        & np.isfinite(sub["Close"]) & sub["Close"].gt(0)
        & np.isfinite(sub["Volume"]) & sub["Volume"].gt(0)
    )
    sub = sub.loc[traded].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", *FIELDS])

    mult = sub["_cum_split"].to_numpy(dtype=np.float64)
    raw_open = np.round(sub["Open"].to_numpy(dtype=np.float64) * mult, 4)
    raw_high = np.round(sub["High"].to_numpy(dtype=np.float64) * mult, 4)
    raw_low = np.round(sub["Low"].to_numpy(dtype=np.float64) * mult, 4)
    raw_close = np.round(sub["Close"].to_numpy(dtype=np.float64) * mult, 4)
    raw_vol = sub["Volume"].to_numpy(dtype=np.float64) / mult

    pre_close = np.empty(len(sub), dtype=np.float64)
    pre_close[0] = raw_open[0]
    if len(sub) > 1:
        pre_close[1:] = raw_close[:-1]

    divs = sub["Dividends"].fillna(0.0).to_numpy(dtype=np.float64) if "Dividends" in sub.columns else np.zeros(len(sub))
    s_vals = (
        sub["Stock Splits"].fillna(0.0).to_numpy(dtype=np.float64)
        if "Stock Splits" in sub.columns
        else np.zeros(len(sub))
    )
    adj_close = (
        sub["Adj Close"].to_numpy(dtype=np.float64)
        if "Adj Close" in sub.columns
        else np.full(len(sub), np.nan)
    )
    for i in range(1, len(sub)):
        if divs[i] > 0 or s_vals[i] > 0:
            p_adj, c_adj = adj_close[i - 1], adj_close[i]
            if np.isfinite(p_adj) and np.isfinite(c_adj) and p_adj > 0 and c_adj > 0:
                derived = round(float(raw_close[i] * (p_adj / c_adj)), 2)
                if derived > 0:
                    pre_close[i] = derived

    out = pd.DataFrame({
        "date": sub.index.to_numpy(dtype=str),
        "open": raw_open,
        "high": raw_high,
        "low": raw_low,
        "close": raw_close,
        "pre_close": pre_close,
        "volume": raw_vol,
        "amount": np.nan,
    })
    out = out.loc[out["date"].isin(set(dates))].copy()
    if out.empty:
        return pd.DataFrame(columns=["date", *FIELDS])
    values = _numeric_bars(out)
    values.insert(0, "date", out.loc[values.index, "date"].tolist())
    return values.reset_index(drop=True)


def _daily_source_history(code: str, dates: list[str]) -> pd.DataFrame:
    """Unadjusted bars from Sina, with the previous close rebuilt from Tencent's qfq series.

    The qfq/raw ratio changes only on an ex-rights date, where the reference
    price is the prior close scaled by that change. Both series are rounded to
    cents, so a change inside the rounding noise is treated as no event: a
    very small dividend on a low-priced stock is missed. Amount is unknown.
    """
    count = (datetime.now(_CN_TZ).date() - date.fromisoformat(dates[0])).days + 10
    raw = _source_frame(code, count, "sina")
    known = raw.index.isin(dates)
    if _is_bse_code(code):
        pre_close = raw["close"].shift().fillna(raw["open"])
    else:
        adjusted = _source_frame(code, count, "tencent")["close"].reindex(raw.index)
        if adjusted[known].isna().any():
            raise PackError(f"Adjusted history does not cover the raw bars for {code}")
        close = raw["close"]
        factor = adjusted / close
        previous = close.shift()
        ratio = factor.shift() / factor
        noise = np.maximum(0.002, 0.012 / adjusted.clip(lower=0.01))
        pre_close = previous.where(~((ratio - 1).abs() > noise), (previous * ratio).round(2))
    bars = raw.assign(pre_close=pre_close.fillna(raw["open"]), amount=np.nan)
    bars = bars.loc[known & raw["volume"].gt(0)]
    values = _numeric_bars(bars)
    values.insert(0, "date", values.index)
    return values.reset_index(drop=True)


def _check_baostock(result) -> None:
    if result.error_code != "0":
        raise PackError(f"Baostock error {result.error_code}: {result.error_msg}")


def _baostock_rows(result) -> Iterator[list[str]]:
    _check_baostock(result)
    while result.next():
        yield result.get_row_data()
    _check_baostock(result)


def _baostock_dates(bs, start: str, end: str) -> list[str]:
    dates = [day for day, is_open in _baostock_rows(bs.query_trade_dates(start_date=start, end_date=end)) if is_open == "1"]
    _check_dates(dates)
    if dates and (dates[0] < start or dates[-1] > end):
        raise PackError("Baostock returned trading dates outside the requested range")
    return dates


def _baostock_universe(bs, first: str, last: str) -> set[str]:
    result = bs.query_stock_basic()
    _check_baostock(result)
    cols = [result.fields.index(key) for key in ("code", "ipoDate", "outDate", "type")]
    codes = set()
    for row in _baostock_rows(result):
        symbol, listed, delisted, kind = (row[i] for i in cols)
        if kind == "1" and (not listed or listed <= last) and (not delisted or delisted >= first):
            code = _code(symbol)
            if code.startswith(_A_SHARE):
                codes.add(code)
    return codes


def _baostock_symbol(code: str) -> str:
    if code.startswith(("4", "8", "920")):
        return f"bj.{code}"
    return _to_baostock_code(code)


def _baostock_history(bs, code: str, first: str, last: str) -> pd.DataFrame:
    result = bs.query_history_k_data_plus(
        _baostock_symbol(code), ",".join(_BAOSTOCK_FIELDS),
        start_date=first, end_date=last, frequency="d", adjustflag="3",
    )
    rows = _baostock_rows(result)
    raw = pd.DataFrame.from_records(rows, columns=list(_BAOSTOCK_FIELDS)).rename(columns={"preclose": "pre_close"})
    _check_dates(raw["date"].tolist())
    raw = raw.loc[raw["tradestatus"] == "1"]
    bars = _numeric_bars(raw)
    bars.insert(0, "date", raw.loc[bars.index, "date"])
    return bars


def _write_history_cache(cache: Path, code: str, bars: pd.DataFrame) -> None:
    dst = cache / f"{code}.csv"
    with TemporaryDirectory(prefix=".history-", dir=cache) as tmp:
        staged = Path(tmp) / dst.name
        bars.to_csv(staged, index=False)
        staged.replace(dst)


def _resume_history(bs, cache: Path, code: str, dates: list[str]) -> pd.DataFrame:
    dst = cache / f"{code}.csv"
    if dst.exists():
        return pd.read_csv(dst, dtype={"date": str, **dict.fromkeys(FIELDS, np.float32)})
    bars = _baostock_history(bs, code, dates[0], dates[-1]) if bs is not None else _daily_source_history(code, dates)
    _history_positions(bars, dates)
    _write_history_cache(cache, code, bars)
    return bars


def _history_positions(bars: pd.DataFrame, dates: list[str]) -> np.ndarray:
    days = bars["date"].to_numpy(dtype=str)
    positions = np.searchsorted(dates, days)
    if (positions >= len(dates)).any() or not np.array_equal(np.asarray(dates)[positions], days):
        raise PackError("Baostock history has bars outside the requested trading sessions")
    return positions


def _backfill_yfinance(
    cache: Path,
    dates: list[str],
    codes: list[str],
    *,
    batch_size: int = _YFINANCE_BATCH_SIZE,
) -> tuple[dict[int, pd.DataFrame], list[str]]:
    results: dict[int, pd.DataFrame] = {}
    yf_failed: list[str] = []
    bse_failed: list[str] = []
    pending: list[tuple[int, str, str]] = []
    bse_pending: list[tuple[int, str]] = []

    for col, code in enumerate(codes):
        dst = cache / f"{code}.csv"
        if dst.exists():
            results[col] = pd.read_csv(dst, dtype={"date": str, **dict.fromkeys(FIELDS, np.float32)})
            continue
        symbol = _to_yahoo_cn_symbol(code)
        if symbol is None:
            bse_pending.append((col, code))
        else:
            pending.append((col, code, symbol))

    max_yf_failures = max(_MAX_FAILED_CODES * max(len(pending), 1), 1)
    start_pad = (date.fromisoformat(dates[0]) - timedelta(days=15)).isoformat()
    end_pad = (date.fromisoformat(dates[-1]) + timedelta(days=3)).isoformat()
    chunks = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]

    for chunk_idx, chunk in enumerate(chunks):
        if chunk_idx > 0 and _YFINANCE_CHUNK_DELAY_SEC > 0:
            time.sleep(_YFINANCE_CHUNK_DELAY_SEC)
        symbols = [sym for _, _, sym in chunk]
        raw = None
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                raw = _yf_download(symbols, start=start_pad, end=end_pad, actions=True)
                last_exc = None
                break
            except ValueError as exc:
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(2.0)
        if last_exc is not None:
            for _, code, _ in chunk:
                yf_failed.append(code)
                logger.warning("yfinance chunk download failed for %s: %s", code, last_exc)
                if len(yf_failed) > max_yf_failures:
                    raise PackError(f"Daily history failed for {len(yf_failed)} codes, aborting") from None
            continue

        for col, code, sym in chunk:
            try:
                sub = _extract_yf_frame(raw, sym, single=len(chunk) == 1)
                if sub.empty or "Close" not in sub.columns or sub["Close"].dropna().empty:
                    raise PackError(f"yfinance returned no daily bars for {sym}")
                bars = _yfinance_bars_from_frame(sub, dates)
                _history_positions(bars, dates)
                _write_history_cache(cache, code, bars)
                results[col] = bars
            except Exception as exc:
                yf_failed.append(code)
                logger.warning("Daily history failed for %s: %s", code, exc)
                if len(yf_failed) > max_yf_failures:
                    raise PackError(f"Daily history failed for {len(yf_failed)} codes, aborting") from None
        if (chunk_idx + 1) % 5 == 0 or chunk_idx + 1 == len(chunks):
            logger.info(
                "yfinance backfill chunk %d/%d: loaded=%d failed=%d",
                chunk_idx + 1,
                len(chunks),
                len(results),
                len(yf_failed),
            )

    if bse_pending:
        def _fetch_bse(item: tuple[int, str]) -> tuple[int, str, pd.DataFrame | None, Exception | None]:
            col, code = item
            try:
                bars = _daily_source_history(code, dates)
                _history_positions(bars, dates)
                _write_history_cache(cache, code, bars)
                return col, code, bars, None
            except Exception as exc:
                return col, code, None, exc

        bse_ok = 0
        with ThreadPoolExecutor(max_workers=min(6, len(bse_pending))) as executor:
            for col, code, bars, exc in executor.map(_fetch_bse, bse_pending):
                if exc is None and bars is not None:
                    results[col] = bars
                    bse_ok += 1
                else:
                    bse_failed.append(code)
                    logger.warning("BSE daily history failed for %s: %s", code, exc)
        logger.info("BSE daily-source backfill complete: ok=%d failed=%d", bse_ok, len(bse_failed))

    return results, [*yf_failed, *bse_failed]


def _backfill_range(
    bs,
    path: Path,
    dates: list[str],
    codes: list[str],
    meta: pd.DataFrame,
    *,
    previous: int = 0,
    mode: str | None = None,
) -> DailyPack:
    resolved_mode = mode or ("baostock" if bs is not None else "daily")
    matrices = _empty_matrices(len(dates), len(codes))
    # Each file is a completed query for this exact date range (including empty results).
    cache = path / ".backfill" / f"{dates[0]}_{dates[-1]}"
    cache.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    max_failures = max(_MAX_FAILED_CODES * len(codes), 1)

    if resolved_mode == "yfinance" and bs is None:
        loaded, failed = _backfill_yfinance(cache, dates, codes)
        for col, bars in loaded.items():
            index = _history_positions(bars, dates)
            for key in FIELDS:
                matrices[key][index, col] = bars[key]
    else:
        for col, code in enumerate(codes):
            try:
                bars = _resume_history(bs, cache, code, dates)
            except Exception as exc:
                # One bad code must not abort a full-market build; it is retried on the next run.
                failed.append(code)
                logger.warning("Daily history failed for %s: %s", code, exc)
                if len(failed) > max_failures:
                    raise PackError(f"Daily history failed for {len(failed)} codes, aborting") from None
                continue
            index = _history_positions(bars, dates)
            for key in FIELDS:
                matrices[key][index, col] = bars[key]
            if (col + 1) % 250 == 0 or col + 1 == len(codes):
                logger.info(
                    "%s backfill progress: %d/%d codes (failed=%d)",
                    resolved_mode,
                    col + 1,
                    len(codes),
                    len(failed),
                )

    close = matrices["close"]
    try:
        _check_coverage(dates, close, previous=previous)
    except _CoverageError as exc:
        # Never mark a provider's incomplete session as permanently fetched.
        missing = np.isnan(close[exc.bad]).any(axis=0)
        for code, retry in zip(codes, missing):
            if retry:
                (cache / f"{code}.csv").unlink(missing_ok=True)
        raise
    source_label = (
        "baostock"
        if resolved_mode == "baostock"
        else ("yfinance" if resolved_mode == "yfinance" else "sina+tencent")
    )
    return DailyPack(
        np.array(dates, dtype="U10"),
        np.array(codes, dtype="U6"),
        matrices,
        meta.reindex(codes).reset_index(),
        (source_label,),
    )


def _latest_snapshot(config: Config) -> pd.DataFrame:
    return fetch_snapshot_with_fallback(config.snapshot_source_priority, required_columns=["code"])


def backfill(
    directory: str | Path | None = None, *, days: int = DEFAULT_DAYS,
    codes_limit: int | None = None, trade_date: str | date | None = None, config: Config | None = None,
    source: str = "auto",
) -> dict:
    """Build the last N CN sessions from resumable per-code daily history.

    ``source`` is ``baostock``, ``yfinance``, ``daily`` (Sina and Tencent
    daily sources) or ``auto``, which uses Baostock when reachable and batched
    yfinance otherwise.
    """
    if days < 1 or (codes_limit is not None and codes_limit < 1):
        raise PackError("days and codes_limit must be positive")
    config = config or Config.from_env()
    path = Path(directory) if directory is not None else pack_dir(config)
    end = _iso_date(trade_date or expected_trade_date())
    start = (date.fromisoformat(end) - timedelta(days=max(2 * days, 30))).isoformat()
    path.mkdir(parents=True, exist_ok=True)
    with _pack_lock(path, write=True):
        snapshot = _latest_snapshot(config)
        meta = _snapshot_meta(snapshot)
        with _history_session(source) as (bs, mode):
            dates = _session_dates(bs, start, end, mode=mode)[-days:]
            if len(dates) != days:
                raise PackError(f"Only {len(dates)} of {days} requested trading sessions are available")
            universe = _baostock_universe(bs, dates[0], dates[-1]) if bs is not None else set()
            codes = sorted(universe | {code for code in meta.index if code.startswith(_A_SHARE)})[:codes_limit]
            pack = _backfill_range(bs, path, dates, codes, meta, mode=mode)
        pack.sources += (_snapshot_source(snapshot),)
        return _save_pack(path, pack)


def update(
    directory: str | Path | None = None, *, trade_date: str | date | None = None,
    days: int = DEFAULT_DAYS, provider: IncrementalProvider | None = None, config: Config | None = None,
    source: str = "auto",
) -> dict:
    """Append the target session and fill earlier gaps from daily history.

    The target session comes from ``provider``; by default TickPlus when
    TICKPLUS_API_KEY is set, then existing snapshot sources, then Tencent
    batch quotes. If none supplies it, the session is rebuilt from daily
    history like any gap.
    """
    if days < 1:
        raise PackError("days must be positive")
    config = config or Config.from_env()
    path = Path(directory) if directory is not None else pack_dir(config)
    end = _iso_date(trade_date or expected_trade_date())
    with _pack_lock(path, write=True):
        pack = _load_pack(path)
        if end <= pack.trade_date:
            return pack.manifest
        last = date.fromisoformat(end)
        first = date.fromisoformat(pack.trade_date) + timedelta(days=1)
        while first.weekday() >= 5:
            first += timedelta(days=1)
        if first > last:
            return pack.manifest

        incremental = None
        if provider is not None:
            providers = [provider]
        else:
            providers = [TickPlusProvider()] if os.getenv("TICKPLUS_API_KEY", "").strip() else []
            providers.append(SnapshotProvider(config))
            providers.append(TencentQuoteProvider(codes=sorted(pack.codes), config=config))
        for provider in providers if last.weekday() < 5 else []:
            try:
                incremental = _normalize_day(provider.fetch_day(end))
            except Exception:
                # Provider exception messages can include request credentials.
                logger.warning("%s could not supply %s, trying the next source", provider.name, end)
                continue
            if not incremental.empty:
                break
            incremental = None
        gap_end = last if incremental is None else last - timedelta(days=1)
        gap = None
        snapshot = None
        if first <= gap_end:
            with _history_session(source) as (bs, mode):
                dates = _session_dates(bs, first.isoformat(), gap_end.isoformat(), mode=mode)
                if dates:
                    snapshot = _latest_snapshot(config)
                    meta = _snapshot_meta(snapshot)
                    codes = set(pack.codes) | {code for code in meta.index if code.startswith(_A_SHARE)}
                    if bs is not None:
                        codes |= _baostock_universe(bs, dates[0], dates[-1])
                    if incremental is not None:
                        codes.update(incremental["code"])
                    previous = int(np.isfinite(pack.matrices["close"][-1]).sum())
                    gap = _backfill_range(
                        bs, path, dates, sorted(codes), meta,
                        previous=previous, mode=mode,
                    )
        if gap is None and incremental is None:
            return pack.manifest
        if snapshot is None:
            snapshot = _latest_snapshot(config)
            meta = _snapshot_meta(snapshot)
        if gap is not None:
            pack = _append(pack, gap, meta, days=days)
        if incremental is not None:
            row = _from_day(end, incremental, meta, provider.name)
            pack = _append(pack, row, meta, days=days)
        pack.sources = tuple(dict.fromkeys((*pack.sources, _snapshot_source(snapshot))))
        return _save_pack(path, pack)
