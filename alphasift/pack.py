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
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from alphasift.config import Config
from alphasift.daily import _BAOSTOCK_LOCK, _to_baostock_code, fetch_daily_history
from alphasift.markets import get_market, latest_settled_close
from alphasift.snapshot import fetch_cn_snapshot, fetch_snapshot_with_fallback

DEFAULT_DAYS = 250
DEFAULT_TAG = "data-cn"
DEFAULT_REPO = "ZhuLinsen/alphasift"
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
}
_REFERENCE_CODES = ("000001", "600519", "601398")
_MAX_FAILED_CODES = 0.05
_PACK_THREAD_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


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
    """Resolve the pack directory from environment and AlphaSift's data dir."""
    config = config or Config.from_env()
    override = os.getenv("ALPHASIFT_PACK_DIR", "").strip()
    return Path(override).expanduser() if override else config.data_dir / "pack" / "cn"


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
        (stage / _MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def stitch_snapshot(pack: DailyPack, snapshot: pd.DataFrame, trade_date: str | date | None = None) -> DailyPack:
    """Return an in-memory pack with a provisional snapshot row appended.

    Requires code, open, high, low, close (or price), pre_close, volume in
    shares, and amount in yuan. Snapshots from sina, efinance and akshare_em
    carry these under their own column names and are mapped automatically;
    em_datacenter and tushare snapshots do not. SnapshotStitchError gives a
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
    repo = repo or os.getenv("ALPHASIFT_PACK_REPO", "").strip() or DEFAULT_REPO
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


def _download(base: str, dst: Path) -> None:
    try:
        with requests.get(f"{base}/{dst.name}", stream=True, timeout=(10, 60)) as response:
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
        login = bs.login()
        _check_baostock(login)
        try:
            yield bs
        finally:
            try:
                bs.logout()
            except Exception:
                logger.warning("Baostock logout failed")


def _baostock_reachable() -> bool:
    try:
        import baostock.common.contants as constants

        with socket.create_connection((constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT), timeout=5):
            return True
    except Exception:
        return False


@contextmanager
def _history_session(source: str = "auto") -> Iterator:
    """Yield a Baostock session, or None to use the existing Sina and Tencent daily sources."""
    if source not in ("auto", "baostock", "daily"):
        raise PackError("history source must be auto, baostock or daily")
    if source == "daily" or (source == "auto" and not _baostock_reachable()):
        if source == "auto":
            logger.warning("Baostock is unreachable, using the Sina and Tencent daily sources")
        yield None
        return
    with _baostock_session() as bs:
        yield bs


def _source_frame(code: str, count: int, source: str) -> pd.DataFrame:
    frame = fetch_daily_history(code, lookback_days=count, source=source, cache_write=False)
    frame = frame.assign(date=pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d"))
    return frame.drop_duplicates("date").set_index("date").sort_index()


def _session_dates(bs, start: str, end: str) -> list[str]:
    if bs is not None:
        return _baostock_dates(bs, start, end)
    count = (datetime.now(_CN_TZ).date() - date.fromisoformat(start)).days + 10
    days: set[str] = set()
    for code in _REFERENCE_CODES:
        try:
            days.update(_source_frame(code, count, "sina").index)
        except Exception as exc:
            logger.warning("Trading calendar reference %s failed: %s", code, exc)
    dates = sorted(day for day in days if start <= day <= end)
    if not dates and not days:
        raise PackError("No daily source returned a trading calendar")
    return dates


def _daily_source_history(code: str, dates: list[str]) -> pd.DataFrame:
    """Unadjusted bars from Sina, with the previous close rebuilt from Tencent's qfq series.

    The qfq/raw ratio changes only on an ex-rights date, where the reference
    price is the prior close scaled by that change. Both series are rounded to
    cents, so a change inside the rounding noise is treated as no event: a
    very small dividend on a low-priced stock is missed. Amount is unknown.
    """
    count = (datetime.now(_CN_TZ).date() - date.fromisoformat(dates[0])).days + 10
    raw = _source_frame(code, count, "sina")
    adjusted = _source_frame(code, count, "tencent")["close"].reindex(raw.index)
    known = raw.index.isin(dates)
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


def _resume_history(bs, cache: Path, code: str, dates: list[str]) -> pd.DataFrame:
    dst = cache / f"{code}.csv"
    if dst.exists():
        return pd.read_csv(dst, dtype={"date": str, **dict.fromkeys(FIELDS, np.float32)})
    bars = _baostock_history(bs, code, dates[0], dates[-1]) if bs is not None else _daily_source_history(code, dates)
    _history_positions(bars, dates)
    with TemporaryDirectory(prefix=".history-", dir=cache) as tmp:
        staged = Path(tmp) / dst.name
        bars.to_csv(staged, index=False)
        staged.replace(dst)
    return bars


def _history_positions(bars: pd.DataFrame, dates: list[str]) -> np.ndarray:
    days = bars["date"].to_numpy(dtype=str)
    positions = np.searchsorted(dates, days)
    if (positions >= len(dates)).any() or not np.array_equal(np.asarray(dates)[positions], days):
        raise PackError("Baostock history has bars outside the requested trading sessions")
    return positions


def _backfill_range(
    bs, path: Path, dates: list[str], codes: list[str], meta: pd.DataFrame, *, previous: int = 0,
) -> DailyPack:
    matrices = _empty_matrices(len(dates), len(codes))
    # Each file is a completed query for this exact date range (including empty results).
    cache = path / ".backfill" / f"{dates[0]}_{dates[-1]}"
    cache.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    for col, code in enumerate(codes):
        try:
            bars = _resume_history(bs, cache, code, dates)
        except Exception as exc:
            # One bad code must not abort a full-market build; it is retried on the next run.
            failed.append(code)
            logger.warning("Daily history failed for %s: %s", code, exc)
            if len(failed) > max(_MAX_FAILED_CODES * len(codes), 1):
                raise PackError(f"Daily history failed for {len(failed)} codes, aborting") from None
            continue
        index = _history_positions(bars, dates)
        for key in FIELDS:
            matrices[key][index, col] = bars[key]
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
    return DailyPack(np.array(dates, dtype="U10"), np.array(codes, dtype="U6"), matrices,
                     meta.reindex(codes).reset_index(), ("baostock" if bs is not None else "sina+tencent",))


def _latest_snapshot(config: Config) -> pd.DataFrame:
    return fetch_snapshot_with_fallback(config.snapshot_source_priority, required_columns=["code"])


def backfill(
    directory: str | Path | None = None, *, days: int = DEFAULT_DAYS,
    codes_limit: int | None = None, trade_date: str | date | None = None, config: Config | None = None,
    source: str = "auto",
) -> dict:
    """Build the last N CN sessions from resumable per-code daily history.

    ``source`` is ``baostock``, ``daily`` (the existing Sina and Tencent
    daily sources) or ``auto``, which uses Baostock when it is reachable.
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
        with _history_session(source) as bs:
            dates = _session_dates(bs, start, end)[-days:]
            if len(dates) != days:
                raise PackError(f"Only {len(dates)} of {days} requested trading sessions are available")
            universe = _baostock_universe(bs, dates[0], dates[-1]) if bs is not None else set()
            codes = sorted(universe | {code for code in meta.index if code.startswith(_A_SHARE)})[:codes_limit]
            pack = _backfill_range(bs, path, dates, codes, meta)
        pack.sources += (_snapshot_source(snapshot),)
        return _save_pack(path, pack)


def update(
    directory: str | Path | None = None, *, trade_date: str | date | None = None,
    days: int = DEFAULT_DAYS, provider: IncrementalProvider | None = None, config: Config | None = None,
    source: str = "auto",
) -> dict:
    """Append the target session and fill earlier gaps from daily history.

    The target session comes from ``provider``; by default TickPlus when
    TICKPLUS_API_KEY is set, then the existing snapshot sources. If none
    supplies it, the session is rebuilt from daily history like any gap.
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
            with _history_session(source) as bs:
                dates = _session_dates(bs, first.isoformat(), gap_end.isoformat())
                if dates:
                    snapshot = _latest_snapshot(config)
                    meta = _snapshot_meta(snapshot)
                    codes = set(pack.codes) | {code for code in meta.index if code.startswith(_A_SHARE)}
                    if bs is not None:
                        codes |= _baostock_universe(bs, dates[0], dates[-1])
                    if incremental is not None:
                        codes.update(incremental["code"])
                    previous = int(np.isfinite(pack.matrices["close"][-1]).sum())
                    gap = _backfill_range(bs, path, dates, sorted(codes), meta, previous=previous)
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
