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
| DES key for Lua (8 B ASCII) | `BUF12SIZ` |

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
- `OBJS.ZU1` (also `OBJS2/3`): rec = 496 B; [0]=icon id (u32), [4]=name, [30]=title, [56]=icon path.
- `WORLDMAPMISSION.ZU1`: rec = 260 B; [0]=id, [4]=name, [132]=name2.
- `TITLE.ZU1`: rec = 924 B; name/desc/requirement/effect.
- **Name-bearing tables** (`ACTIONS`, `ACTTYPEINFO`, `CAVERNTEMPLATE`, `FORMULA`,
  `ITEMS*`, `MAPS`, `MOTION`, `MUSICINFO`, `REFINE*`, `SPELL*`, `TALENTS`, …):
  each fixed record is `u32 id` + a name string at a fixed offset (4, or 8 for
  `SPELL`/`SPELLS`/`ITEMATT`). See `zudata._NAME_AT`.
- `RESOURCE.ZU1`: a resource-path list; framing is `id/type/len + name` but the
  per-record padding is not fully stable, so `zudata.dump_resource` extracts the
  path strings directly.
- Plaintext config tables (`CREED` XML; `ERROR*` TSV; `FLIGHT`, `GMHELP`,
  `HELPMANAGED`, `MISSION`, `SHOPCITYHELP`, `STORYCARD` INI; `TUTORIAL` text) are
  written as-is with a sniffed extension — see `zudata.TEXT_TABLES`.

Reader: `zudata.py`.

### Map images (`/MAPS`)

- `*.ZU3` = raw **JPEG** minimap/world images (`FF D8 FF E1`) — no container,
  rename to `.jpg` to view.
- `*.ZU2` = the same `FDCA2121` RC4+LZO1X container; the payload is a
  **1024×1024 16-bit BMP heightmap** (`"BM"` header). Decode with
  `zudata.decode_zu1`.

## 3. `WORLDS/*.DAT` (LithTech Jupiter world, `.DAT` version 85)

Header (from LithTech `tools/PreProcessor/.../PCWorldPacker.cpp`, `CURRENT_DAT_VERSION=85`):
```
u32 version (=85)
u32 object_section_offset      ; object stream starts here
u32 blind_data_offset          ; == end of object section
u32 light_grid_offset          ; == end of blind-data section
u32 physics_offset             ; == end of light-grid section
u32 particle_offset            ; == end of physics section
u32 render_offset              ; == end of particle section
u32 reserved[8]                ; zero
u32 info_len ; char info[info_len]        ; world info / light-table string
float pos_min[3] ; pos_max[3] ; world_offset[3]
```
Section order in the file: WorldTree, WorldModels (both sit between the header
and the object section and are *unmarked*), then objects, blind data, light grid,
physics, particle, render. The object section is the range
`object_section_offset`..`blind_data_offset`.

Object stream:
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

## 4. Lua scripts (`/SCRIPT/*.LUA`)

```
b"Rar!lua!" | u32 original_size | ciphertext (padded up to an 8-byte multiple)
```
The payload is **DES in ECB mode** (decrypt direction), key `"BUF12SIZ"`.

It is a *vanilla DES* algorithm (standard S-boxes/SP-boxes), implemented with
precomputed bit-permutation tables and a **non-standard PC1**; the client ships
its own tables, so re-implement it against the dumped tables rather than using a
stock DES library. Tables in `client.lto`:
- PC1 `0x10500ba0` (56 B), key-shift `0x10500b90` (16 B)
- PC2 `0x10500bd8` (24 B, for D) / `0x10500bf0` (24 B, for C)
- SP-boxes `0x10500c08`..`0x10501308` (8 × 64 dwords) — standard DES SP values
- IP `0x10501408` / IP2 `0x10501808` / FP `0x10501c08` / FP2 `0x10502008` (256 dwords each)
- subkey scratch `0x105acf50`

Key schedule `0x102a34f0`, block `0x102a3760`, wrapper `0x102a3c30`,
key-builder `0x101ebcf0` (concatenates `"BUF"`,`"12"`,`"SIZ"`), loader `0x101ebe10`.

Reader: `zulua.py` (`decrypt_blob`, `dumpall`, selftest).

## 5. `Rar!Bute` container — OPEN

`FLYSWORDBOOK.ZU1` and `MISSION3.ZU1` (in `/DATA`) are stored in a second
container: magic `"Rar!Bute"` (8 B) + encrypted body. The magic string sits at
VA `0x103fd218` next to the `"CGameButeMgr"` error strings. The Lua DES key
`BUF12SIZ`, RC4(`RC4_KEY`) and plain LZO all produce garbage, so the cipher/key
is still unknown. Not decoded.
