"""BLAKE3 σε καθαρή Python (βάσει της επίσημης reference implementation, CC0).
Χρησιμοποιείται μόνο αν δεν υπάρχει το πακέτο blake3."""
OUT_LEN = 32
KEY_LEN = 32
BLOCK_LEN = 64
CHUNK_LEN = 1024
CHUNK_START = 1 << 0
CHUNK_END = 1 << 1
PARENT = 1 << 2
ROOT = 1 << 3
IV = [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]
MSG_PERMUTATION = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]
M32 = 0xFFFFFFFF


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & M32


def _g(s, a, b, c, d, mx, my):
    s[a] = (s[a] + s[b] + mx) & M32
    s[d] = _rotr(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & M32
    s[b] = _rotr(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b] + my) & M32
    s[d] = _rotr(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & M32
    s[b] = _rotr(s[b] ^ s[c], 7)


def _round(s, m):
    _g(s, 0, 4, 8, 12, m[0], m[1]); _g(s, 1, 5, 9, 13, m[2], m[3])
    _g(s, 2, 6, 10, 14, m[4], m[5]); _g(s, 3, 7, 11, 15, m[6], m[7])
    _g(s, 0, 5, 10, 15, m[8], m[9]); _g(s, 1, 6, 11, 12, m[10], m[11])
    _g(s, 2, 7, 8, 13, m[12], m[13]); _g(s, 3, 4, 9, 14, m[14], m[15])


def _compress(cv, block_words, counter, block_len, flags):
    s = list(cv) + IV[:4] + [counter & M32, (counter >> 32) & M32, block_len, flags]
    m = list(block_words)
    for r in range(7):
        _round(s, m)
        if r < 6:
            m = [m[i] for i in MSG_PERMUTATION]
    for i in range(8):
        s[i] ^= s[i + 8]
        s[i + 8] ^= cv[i]
    return s


def _words(b):
    b = b.ljust(BLOCK_LEN, b"\0")
    return [int.from_bytes(b[i:i + 4], "little") for i in range(0, BLOCK_LEN, 4)]


class _Output:
    def __init__(self, cv, bw, counter, block_len, flags):
        self.cv, self.bw, self.counter, self.block_len, self.flags = cv, bw, counter, block_len, flags

    def chaining_value(self):
        return _compress(self.cv, self.bw, self.counter, self.block_len, self.flags)[:8]

    def root_bytes(self, n):
        out, c = b"", 0
        while len(out) < n:
            w = _compress(self.cv, self.bw, c, self.block_len, self.flags | ROOT)
            out += b"".join(x.to_bytes(4, "little") for x in w)
            c += 1
        return out[:n]


class _Chunk:
    def __init__(self, key, counter, flags):
        self.cv, self.counter, self.flags = list(key), counter, flags
        self.block, self.blocks_compressed, self.len_total = b"", 0, 0

    def start_flag(self):
        return CHUNK_START if self.blocks_compressed == 0 else 0

    def update(self, data):
        while data:
            if len(self.block) == BLOCK_LEN:
                self.cv = _compress(self.cv, _words(self.block), self.counter, BLOCK_LEN,
                                    self.flags | self.start_flag())[:8]
                self.blocks_compressed += 1
                self.block = b""
            take = min(BLOCK_LEN - len(self.block), len(data))
            self.block += data[:take]
            self.len_total += take
            data = data[take:]

    def output(self):
        return _Output(self.cv, _words(self.block), self.counter, len(self.block),
                       self.flags | self.start_flag() | CHUNK_END)


def _parent(l, r, key, flags):
    return _Output(key, l + r, 0, BLOCK_LEN, PARENT | flags)


def blake3_hex(data, length=32):
    key, flags = IV, 0
    stack, chunk = [], _Chunk(key, 0, flags)
    while data:
        if chunk.len_total == CHUNK_LEN:
            cv = chunk.output().chaining_value()
            total = chunk.counter + 1
            while total & 1 == 0:
                cv = _parent(stack.pop(), cv, key, flags).chaining_value()
                total >>= 1
            stack.append(cv)
            chunk = _Chunk(key, chunk.counter + 1, flags)
        take = min(CHUNK_LEN - chunk.len_total, len(data))
        chunk.update(data[:take])
        data = data[take:]
    out = chunk.output()
    for cv in reversed(stack):
        out = _parent(cv, out.chaining_value(), key, flags)
    return out.root_bytes(length).hex()
