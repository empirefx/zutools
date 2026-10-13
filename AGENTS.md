# AGENTS.md — maintainer notes for `zutools`

This package decodes the *Zu Online / 新蜀山OL* client data. It was built from
static reverse-engineering of the shipped client; every format claim in
`docs/FORMATS.md` was validated against real data. If you refactor, re-run the
self-checks below before committing.

## Ground rules

- **Pure standard library.** Do not add dependencies. The env has no C compiler
  and no `python-lzo`; LZO1X is implemented in `zucrypto.lzo1x_decompress`.
- **Keys live in `zucrypto.py`** (ChaCha20 key/nonce, `RC4_KEY`). Never inline
  them elsewhere.
- **Report unknowns honestly.** The Lua `"Rar!lua!"` cipher is NOT implemented
  (see TODO). Don't fake it.

## Self-checks (run before/after changes)

```powershell
python -c "from zucrypto import lzo1x_decompress; print('lzo ok')"
# ChaCha20 all-zero vector must equal:
#   76b8e0ada0f13d90405d6ae55386bd28bdd219b8a08ded1aa836efcc8b770dc7
python zudata.py decode DATA\ACTIONS.ZU1 $env:TEMP\actions.bin   # 444 bytes
python zuworld.py list WORLDS\XR.DAT                             # 31 objects
```

Known-good expectations:
- `ACTIONS.ZU1` decodes to **444** bytes.
- `AREATABLE.ZU1` decodes to **4** bytes.
- `XR.DAT` parses to **31** objects (11 `ZUWorldModel`, 10 `SpecialFX`, 4 `GameStartPoint`, …).
- `LEVEL01_00_WYC.DAT` parses to **807** objects.

## Data provenance (how each format was found)

- **ChaCha20**: reference block fn in `d3dx9_24.dll` @`0x100022d0`; keystream is
  indexed by *absolute file offset* (counter = `offset>>6`). Do not "fix" this to
  be contiguous — the archive relies on the offset indexing.
- **`.zu1` = RC4 + LZO1X**: RC4 fn `0x102a1e40` (state = 256-byte S-box + i/j
  at `+0x100/+0x101`), LZO fn `0x102a4c10`, in `client.lto`. Key copied from the
  15-byte constant @`0x10502408`.
- **REZ block format**: LithTech; stored type string is reversed on disk.
- **`.DAT` object stream**: value = `u8 tag + u32 flags + u16 size + data`;
  `Pos`/`Dims` are 3 floats. Objects are separated by a `u16` marker and the
  stream is prefixed by a `u32` count.

## TODO / open items

- **Lua `"Rar!lua!"` container**: 8-byte block cipher, a *custom* DES variant
  (client PC1 table @`0x10500ba0` ≠ standard DES; shifts @`0x10500b90` do match).
  Key is built from the `"SIZ"`,`"12"`,`"BUF"` strings near `0x101ebcf0`.
  Lua decrypt entry `0x101ebe10`. Not yet reproduced.
- `zudata.LAYOUTS` only covers a few tables; add layouts as more are decoded
  (record count is always the u32 at offset 0).
- `.DAT` header offset table (after the initial `0x55` u32) is only partially
  understood; the object stream is found via the 2nd offset.

## Code map

- `zurez.Archive.entries()` yields `(path, size, read_pos)`; `Archive.read()`
  fetches bytes (handles the seal boundary transparently).
- `zudata.decode_zu1(blob)` is the single entry point for `.zu1` bytes.
- `zuworld.parse_objects(blob, start)` returns `[(class, {prop: bytes})]`.
