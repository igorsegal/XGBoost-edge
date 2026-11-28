import struct, datetime as dt
UTC = dt.timezone.utc
def xf(path):
    b = open(path, 'rb').read(); per, = struct.unpack('<i', b[16:20]); pt, = struct.unpack('<d', b[24:32]); n, = struct.unpack('<q', b[32:40]); sl, = struct.unpack('<i', b[56:60]); off = 60 + sl
    R = list(struct.iter_unpack('<qddddqiq', b[off:off + 60 * n])); return per, pt, [(r[0], r[1], r[2], r[3], r[4], r[6]) for r in R]
def hst(path):
    b = open(path, 'rb').read(); assert struct.unpack('<i', b[:4])[0] == 401
    return [struct.unpack('<qdddd', b[p:p+40]) for p in range(148, len(b) - 59, 60)]
def d(t): return dt.datetime.fromtimestamp(t, UTC).strftime('%Y-%m-%d %H:%M')
