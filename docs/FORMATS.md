# Zu Online (新蜀山OL) client formats — reverse-engineered reference

Game: *Zu Online / 新蜀山OL* (Onwind Digital, ~2005–2008), LithTech Jupiter engine.
All facts below were recovered by static analysis of `client.lto`, the two
sealed `d3dx9_2x.dll` proxy DLLs, and validated against real shipped archives.

## Keys (hardcoded in the client)

| Purpose | Value |
|---|---|
| ChaCha20 key (32 B) | `e70784ff0ede84ef732627e967fbae07fd4ed99a7dddca8f16664cb9e5eeee17` |
| ChaCha20 nonce (12 B) | `48a63a2be3e374103dd3819e` |
| RC4 key for `.zu1` (15 B) | `21eff8e89f31d52fd284d8ff0fc3f4` |

Source offsets in `client.lto`:
- ChaCha20 reference: `d3dx9_24.dll` const `"expand 32-byte k"` @`0x10002540`, block fn `0x100022d0`.
- RC4 (`0x102a1e40`, 256-byte S-box + i/j @+0x100/+0x101) then LZO1X (`0x102a4c10`).
  The RC4 key is copied from the 15-byte constant @`0x10502408`;
  the `.zu1` magic/version string sits @`0x10402e98` (`Fd ca 21 21`, `"2.02"`, `"Oct 17 2005"`).

## 1. `.zu` archives (RezMgr v1)

LithTech REZ container. The header (first `0x100` bytes) and the tail region
are XOR-encrypted with **ChaCha20**, where the keystream is indexed by the
**absolute file offset** of each byte (counter = `offset >> 6`). The record
data region itself is **plaintext** — resource payloads are stored
UNCOMPRESSED.

Header fields (little-endian):
- `0x83` (8 bytes): `RootDirPos` (u32) + `RootDirSize` (u32) — encrypted.
- `0x8f` (u32): `NextWritePos` (the seal boundary — start of the sealed tail).

REZ block format (after ChaCha20 is removed):
```
block   : u32 type (0=resource,1=directory), u32 pos, u32 size, u32 time
resource: u32 id, char type[4] (NUL-padded), u32 num_keys, cstr name,
          cstr description, u32 keys[num_keys]
directory: cstr name           ; sub-block read at (pos,size)
```
The stored 4-char **type is the real extension reversed**: `XTD→DTX`,
`BTL→LTB`, `RPS→SPR`, `VAW→WAV`, `AUL→LUA`, `3UZ→ZU3`, `3PM→MP3`,
`GPJ→JPG`, `1UZ→ZU1`, `2UZ→ZU2`, `XSLX→XLSX`, `LLD→DLL`.

Reader: `zurez.py` (`Archive`, `extract`).

## 2. `.zu1` data tables (`/DATA`, `/ATTRIBUTES`, …)

Container:
```
u32 magic = 0x2121CAFD ("Fd ca 21 21") ; u32 flags ; u32 original_size ; payload
```
`payload = LZO1X( RC4(payload_ciphertext, key=RC4_KEY) )`.

If the first 4 bytes are **not** the magic, the file is a plaintext table whose
first u32 is the record count. Most gameplay tables (OBJS, KEYWORDDATA,
WORLDMAPMISSION, MISSION, RESOURCE, TITLE, …) are plaintext; the resource-heavy
ones (ITEMS, SPELL, FORMULA, …) are compressed.

Record layouts recovered so far (record count = u32 at offset 0):
- `KEYWORDDATA.ZU1`: rec = 24-byte header + 11 × 255-byte fields.
  field 0 = `"x,y,z"` world coord, field 10 = name; fields 1–9 = extra coords.
- `OBJS.ZU1`: rec = 496 B; [0]=icon id (u32), [4]=name, [30]=title, [56]=icon path.
- `WORLDMAPMISSION.ZU1`: rec = 260 B; [0]=id, [4]=name, [132]=name2.
- `TITLE.ZU1`: rec = 924 B; name/desc/requirement/effect.

Reader: `zudata.py`.

### Map images (`/MAPS`)

- `*.ZU3` = raw **JPEG** minimap/world images (`FF D8 FF E1`) — no container,
  rename to `.jpg` to view.
- `*.ZU2` = the same `FDCA2121` RC4+LZO1X container; the payload is a
  **1024×1024 16-bit BMP heightmap** (`"BM"` header). Decode with
  `zudata.decode_zu1`.

## 3. `WORLDS/*.DAT` (LithTech Jupiter world)

Header: `u32 0x55` then a table of u32 section offsets. The 2nd offset points at
the object stream:
```
stream : u32 object_count, then object_count × [ u16 marker, object ]
object : u16 classlen, class[classlen], u32 propcount, prop × propcount
prop   : u16 namelen, name[namelen], value
value  : u8 tag, u32 flags, u16 size, size bytes
```
Values used here: `Name` (u16-len string), `Pos`/`Dims` (3× float32 xyz),
`Rotation` (4× float32). Classes seen: `GameStartPoint`, `AIVolume`,
`ZUWorldModel`, `Light`, `SpecialFX`, `SkyPointer`, … (server-side NPC/monster
spawns are NOT in the client `.DAT`; those live in `KEYWORDDATA`).

Reader: `zuworld.py`.

## 4. Lua scripts

Stored as `"Rar!lua!"` (8 B) + u32 original_size + an **8-byte block cipher**
payload (a custom DES variant — the client's PC1 table @`0x10500ba0` differs
from standard DES). Not yet reproduced; see `/docs` TODO.
