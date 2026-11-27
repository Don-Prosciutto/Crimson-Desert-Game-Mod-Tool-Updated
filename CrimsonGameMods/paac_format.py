"""PAAC action chart (.paac) reader/writer - own implementation, CrimsonGameMods.

Reads and writes every action chart of the game byte-exact (558 files checked,
game 2.05.00 and 2.06.00, 559 files each; not commonactioninfo*.paac, which is another format). No Qt in here.

Layout (little-endian):
  u32 node_count
  node x node_count: f32 blend, then from f32 duration a 110-byte head (+4 tag hash,
      +8 flags, +66 u16 mask name index), 10 x (u16 count, u16 end) slot table,
      u16 z, 12 fixed bytes (u16 anim, u16 anim2 = index in the .paa list, ...),
      slot data (end[9] bytes; element sizes 12/16/104/160/24/36/12/96/?/12),
      z x 16 bytes, u8 n, n x 20-byte timed events
      (f32 time, f32 -1, u32 word offset in the event blob, u32 seq, u16 ffff, u16 1).
      Variants (e.g. tag "wyvern") follow their base node directly.
  u32 P + P x (u32 id, u32 value); u32 + hash list A; u32 + hash list B
  10 string lists: u16 n, n x (u8 length incl. 0, bytes)
      [0 pool (keys, masks), 1 .paa, 2 .paa camera, 3 effects, 4 ?, 5 motionblending,
       6 bones, 7 masks, 8 baseseq, 9 ?]
  40-byte head (18 bytes since game 2.06), u16 nh, nj, k, m, x; nh x u32; k x u16; nj x 40;
  m x 288-byte state records (+24 name hash, +84 u16 node index,
      +228/+232 u16 start/count in S6b, +238 movement mode); x x 12
  D1: u32 bytes + condition bytecode (u32 words, prefix: 651 AND, 652 OR, 653 NOT,
      5-word checks e.g. 234 key [pool index, hash, 0, 0], 311 tag [0, hash, 0, 0])
  D2: u32 n + n x u16 word offsets into D1 (one per instruction)
  S5: u32 n + n x 56 transitions (+8 f32 blend, +20 target record hash, +28 kind,
      +36/+42 condition A start/count in D2, +38/+43 condition B, +40 input id)
  S6a: u32 n + n x 8; S6b: u32 n + n x 32 (state entry lists; +12 index in S5,
      or with a hash at +0 a branch group)
  S7: u16 n + n x 28; S8: u32 n + n x 8; 5 bytes; u32 bytes + event blob; trailer
"""
import struct

HASH_INIT = 0xC5EDE   # engine name hash: Jenkins lookup3 hashlittle, start value 0xC5EDE


def lookup3(s, init=HASH_INIT):
    if isinstance(s, str):
        s = s.encode()
    M = 0xffffffff
    def rot(x, k): return ((x << k) | (x >> (32 - k))) & M
    length = len(s); a = b = c = (0xdeadbeef + length + init) & M; i = 0
    while length > 12:
        a = (a + int.from_bytes(s[i:i + 4], 'little')) & M
        b = (b + int.from_bytes(s[i + 4:i + 8], 'little')) & M
        c = (c + int.from_bytes(s[i + 8:i + 12], 'little')) & M
        a = (a - c) & M; a ^= rot(c, 4); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 6); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 8); b = (b + a) & M
        a = (a - c) & M; a ^= rot(c, 16); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 19); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 4); b = (b + a) & M
        length -= 12; i += 12
    if length == 0:
        return c
    t = s[i:] + b'\0' * 12
    a = (a + int.from_bytes(t[0:4], 'little')) & M
    b = (b + int.from_bytes(t[4:8], 'little')) & M
    c = (c + int.from_bytes(t[8:12], 'little')) & M
    c ^= b; c = (c - rot(b, 14)) & M
    a ^= c; a = (a - rot(c, 11)) & M
    b ^= a; b = (b - rot(a, 25)) & M
    c ^= b; c = (c - rot(b, 16)) & M
    a ^= c; a = (a - rot(c, 4)) & M
    b ^= a; b = (b - rot(a, 14)) & M
    c ^= b; c = (c - rot(b, 24)) & M
    return c



SLOT_SZ = [12, 16, 104, 160, 24, 36, 12, 96, None, 12]

class Paac:
    pass

def _u16(d, o): return struct.unpack_from('<H', d, o)[0]
def _u32(d, o): return struct.unpack_from('<I', d, o)[0]

# Game 2.06.00 shortened the 40-byte block after the string lists to 18 bytes
# and inserted three condition opcodes before AND/OR/NOT (651-653 -> 654-656).
HEAD_LEN = {"2.06": 18, "2.05": 40}
COND_OPS = {"2.06": (654, 655, 656), "2.05": (651, 652, 653)}   # AND, OR, NOT


def _need(d, o, size):
    if size < 0 or o + size > len(d):
        raise ValueError("paac: section runs past the end of the file")


def parse(d, layout=None):
    """Read a .paac; p.layout is the game layout ("2.06" or "2.05"), p.cond_ops
    the AND/OR/NOT opcodes of that layout. Without a layout the current game's
    (2.06) is tried first; 2.05 only when the file does not fit it (all 559
    charts of 2.06.00 read as 2.06, a few 2.05 files would also fit 2.06 - pass
    layout="2.05" for old files)."""
    err = None
    for lay in ((layout,) if layout else ("2.06", "2.05")):
        try:
            p = _parse(d, HEAD_LEN[lay])
        except (ValueError, IndexError, struct.error) as e:
            err = e
            continue
        p.layout = lay
        p.cond_ops = COND_OPS[lay]
        return p
    raise ValueError("unknown action chart layout: %s" % err)


def _parse(d, head_len):
    p = Paac(); o = 0
    n = _u32(d, 0); o = 4
    p.nodes = []
    for _ in range(n):
        b = o + 4
        tab = struct.unpack_from('<20H', d, b + 110)
        z = _u16(d, b + 150)
        o2 = b + 164 + tab[19] + 16 * z
        nt = d[o2]; o3 = o2 + 1 + 20 * nt
        p.nodes.append(d[o:o3]); o = o3
    P = _u32(d, o); o += 4; _need(d, o, 8 * P)
    p.pairs = [struct.unpack_from('<II', d, o + 8 * i) for i in range(P)]; o += 8 * P
    nA = _u32(d, o); _need(d, o + 4, 4 * nA); p.A = list(struct.unpack_from('<%dI' % nA, d, o + 4)); o += 4 + 4 * nA
    nB = _u32(d, o); _need(d, o + 4, 4 * nB); p.B = list(struct.unpack_from('<%dI' % nB, d, o + 4)); o += 4 + 4 * nB
    p.lists = []
    for _ in range(10):
        c = _u16(d, o); o += 2; L = []
        for _ in range(c):
            ln = d[o]; L.append(d[o + 1:o + ln]); o += 1 + ln   # without the 0 byte
        p.lists.append(L)
    _need(d, o, head_len + 10); p.chead = d[o:o + head_len]; o += head_len
    nh, nj, k, m, x = struct.unpack_from('<5H', d, o); o += 10
    _need(d, o, 4 * nh + 2 * k + 40 * nj + 288 * m + 12 * x)
    p.hashes = list(struct.unpack_from('<%dI' % nh, d, o)); o += 4 * nh
    p.klist = list(struct.unpack_from('<%dH' % k, d, o)); o += 2 * k
    p.jblocks = [d[o + 40 * i:o + 40 * i + 40] for i in range(nj)]; o += 40 * nj
    p.records = [d[o + 288 * i:o + 288 * i + 288] for i in range(m)]; o += 288 * m
    p.xblocks = [d[o + 12 * i:o + 12 * i + 12] for i in range(x)]; o += 12 * x
    nb = _u32(d, o); _need(d, o + 4, nb); p.D1 = d[o + 4:o + 4 + nb]; o += 4 + nb
    n2 = _u32(d, o); _need(d, o + 4, 2 * n2); p.D2 = list(struct.unpack_from('<%dH' % n2, d, o + 4)); o += 4 + 2 * n2
    n5 = _u32(d, o); _need(d, o + 4, 56 * n5); p.S5 = [d[o + 4 + 56 * i:o + 4 + 56 * i + 56] for i in range(n5)]; o += 4 + 56 * n5
    n6 = _u32(d, o); _need(d, o + 4, 8 * n6); p.S6a = [d[o + 4 + 8 * i:o + 12 + 8 * i] for i in range(n6)]; o += 4 + 8 * n6
    n6 = _u32(d, o); _need(d, o + 4, 32 * n6); p.S6b = [d[o + 4 + 32 * i:o + 36 + 32 * i] for i in range(n6)]; o += 4 + 32 * n6
    n7 = _u16(d, o); _need(d, o + 2, 28 * n7); p.S7 = [d[o + 2 + 28 * i:o + 30 + 28 * i] for i in range(n7)]; o += 2 + 28 * n7
    n8 = _u32(d, o); _need(d, o + 4, 8 * n8); p.S8 = [d[o + 4 + 8 * i:o + 12 + 8 * i] for i in range(n8)]; o += 4 + 8 * n8
    p.gap5 = d[o:o + 5]; o += 5
    nb = _u32(d, o); _need(d, o + 4, nb); p.blob = d[o + 4:o + 4 + nb]; o += 4 + nb
    p.trailer = d[o:]
    return p

def build(p):
    out = bytearray()
    out += struct.pack('<I', len(p.nodes))
    for nd in p.nodes: out += nd
    out += struct.pack('<I', len(p.pairs))
    for a, b in p.pairs: out += struct.pack('<II', a, b)
    out += struct.pack('<I', len(p.A)) + struct.pack('<%dI' % len(p.A), *p.A)
    out += struct.pack('<I', len(p.B)) + struct.pack('<%dI' % len(p.B), *p.B)
    for L in p.lists:
        out += struct.pack('<H', len(L))
        for s in L: out += bytes([len(s) + 1]) + s + b'\x00'
    out += p.chead
    out += struct.pack('<5H', len(p.hashes), len(p.jblocks), len(p.klist), len(p.records), len(p.xblocks))
    out += struct.pack('<%dI' % len(p.hashes), *p.hashes)
    out += struct.pack('<%dH' % len(p.klist), *p.klist)
    for b in p.jblocks: out += b
    for b in p.records: out += b
    for b in p.xblocks: out += b
    out += struct.pack('<I', len(p.D1)) + p.D1
    out += struct.pack('<I', len(p.D2)) + struct.pack('<%dH' % len(p.D2), *p.D2)
    for L, w in ((p.S5, 4), (p.S6a, 4), (p.S6b, 4)):
        out += struct.pack('<I', len(L))
        for b in L: out += b
    out += struct.pack('<H', len(p.S7))
    for b in p.S7: out += b
    out += struct.pack('<I', len(p.S8))
    for b in p.S8: out += b
    out += p.gap5
    out += struct.pack('<I', len(p.blob)) + p.blob
    out += p.trailer
    return bytes(out)
