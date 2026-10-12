"""Checagem da leitura de estado do sitter. Rode: python test_sitter.py"""
import struct
import time

import sitter_fi as s


def dac(le_state=0, le_flags=0, pb_state=0, pb_flags=0, rate=0, age=0, ctrl="livre", fw="ed4-354-x",
        ip="192.168.0.80", via="192.168.0.132", mac="8a9e36988cce"):
    status = struct.pack("<BBBBHHHHII", 0, le_state, pb_state, 0, le_flags, pb_flags, 0, 100, rate, 0)
    pkt = bytes.fromhex(mac) + struct.pack("<HHHI", 30, 3, 3839, 180000) + status
    d = s.Dac(s.Broadcast(pkt, (ip, 7654), via))
    d.bc.time -= age
    d.ctrl, d.ctrl_time, d.firmware = ctrl, time.time(), fw
    return d


def rows(d, nets=None):
    return {n: vc for (_t, names), values in zip(s.GROUPS, s.params(d, now, nets))
            for n, vc in zip(names, values)}


now = time.time()
NETS = {"192.168.0.132": ("255.255.255.0", "Wi-Fi")}

# estado geral
assert s.health(dac(), now)[:2] == (s.OK, "OPERACIONAL")
assert s.health(dac(age=10), now)[:2] == (s.OFF, "OFFLINE")
c, t, why = s.health(dac(le_state=3, le_flags=0b10110), now)  # interlock aberto
assert (c, t) == (s.ERR, "E-STOP") and why.index("interlock aberto") < why.index("disparado")
assert s.health(dac(ctrl="recusada"), now)[1] == "OCUPADA"
assert s.health(dac(ctrl="sem resposta"), now)[1] == "SEM CONTROLE"
old = dac(ctrl="sem resposta")
old.ctrl_time -= s.CTRL_TTL + 1
assert s.health(old, now)[1] == "OPERACIONAL"            # resultado TCP velho não manda mais
assert s.health(dac(ctrl="sem resposta", pb_state=2), now)[1] == "TOCANDO"
assert s.health(dac(pb_state=2, rate=30000), now)[:2] == (s.BUSY, "TOCANDO")
assert s.health(dac(pb_state=1), now)[1] == "PREPARADA"

# flag de rede do MadMapper
assert s.health(dac(le_state=3, le_flags=1, pb_state=2, rate=20000), now)[:2] == (s.BUSY, "TOCANDO")
assert s.health(dac(le_state=3, le_flags=1), now)[:2] == (s.WARN, "E-STOP")
assert s.health(dac(le_state=3, le_flags=5, pb_state=2), now)[:2] == (s.ERR, "E-STOP")
assert s.health(dac(le_state=3, le_flags=0), now)[:2] == (s.ERR, "E-STOP")
assert rows(dac(le_state=3, le_flags=1, pb_state=2))["Laser"] == ("liberado · flag de rede", s.OK)

# parâmetros
r = rows(dac(le_state=3, le_flags=4 | 2))
assert r["Interlock"] == ("ABERTO", s.ERR) and r["Laser"] == ("E-STOP", s.ERR)
assert rows(dac(fw=None, ctrl="recusada"))["Firmware"][0] == "não lido (recusada)"
assert rows(dac(fw="ed4-152-33b3cef"))["Atualização"] == ("ed4-354 disponível", s.WARN)
assert rows(dac(), NETS)["Placa do PC"] == ("Wi-Fi · 192.168.0.132", s.OK)

# rede: faixa e IP duplicado
a, b = dac(), dac(mac="000000000001")
assert s.net_issue(a, [a], NETS, now) is None
far = dac(ip="10.0.0.5")
assert s.net_issue(far, [far], NETS, now) == "faixa"
assert s.net_issue(a, [a, b], NETS, now) == "duplicado"
b.bc.time -= 10                                           # a outra está offline: sem conflito
assert s.net_issue(a, [a, b], NETS, now) is None
far.net = "faixa"
assert s.health(far, now)[1] == "FAIXA ERRADA"
assert rows(far, NETS)["Faixa"] == ("fora · PC em 192.168.0.0/24", s.WARN)
assert s.suggest_ip("192.168.0.132", "255.255.255.0", {"192.168.0.50"}) == ("192.168.0.51", "255.255.255.0", "192.168.0.1")
assert s.suggest_ip("169.254.10.3", "255.255.0.0", set())[0] == "169.254.0.50"
assert s.suggest_pc_ip("10.0.0.5") == "10.0.0.10" and s.suggest_pc_ip("10.0.0.10") == "10.0.0.11"

# Clear E-Stop: a ED4 dá ACK mesmo sem E-stop
def st(le):
    return b"a?" + struct.pack("<BBBBHHHHII", 0, le, 0, 0, 0, 0, 0, 0, 0, 0)
assert s.clear_result(st(3), b"ac" + st(0)[2:]) == ("E-stop limpo", None)
assert s.clear_result(st(0), b"ac" + st(0)[2:]) == ("não estava em E-stop", None)
assert s.clear_result(st(3), b"ac" + st(3)[2:]) == ("ACK, mas continua em E-stop", None)
assert s.clear_result(st(3), b"!c" + st(3)[2:])[0].startswith("NAK")
assert s.clear_result(st(3), b"\xffc" + st(3)[2:]) == ("resposta desconhecida %r", b"\xff")

assert s.fw_update("ed4-152-33b3cef") == "ed4-354"
assert s.fw_update("ed4-354-0d43ec7") is None
assert s.fw_update("ed3v80-abc") == "ed3v86"
assert s.fw_update("r331-ed4bef5") is None

# nomes: salvar e reler (arquivo temporário)
import os, tempfile
s.NAMES_FILE = os.path.join(tempfile.mkdtemp(), "nomes.json")
assert s.load_names() == {}
assert s.save_names({"8a9e36988cce": "PALCO ESQ"}) is None
assert s.load_names() == {"8a9e36988cce": "PALCO ESQ"}

# macOS: placas a partir do ifconfig / networksetup
IFC = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 3c:22:fb:00:00:01
\tinet 192.168.0.20 netmask 0xffffff00 broadcast 192.168.0.255
en7: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 169.254.33.7 netmask 0xffff0000 broadcast 169.254.255.255
"""
PORTS = "Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: 3c:22:fb:00:00:01\n"
nets, devs = s.parse_ifconfig(IFC, PORTS)
assert nets == {"192.168.0.20": ("255.255.255.0", "Wi-Fi"), "169.254.33.7": ("255.255.0.0", "en7")}
assert devs == {"en0": "192.168.0.20", "en7": "169.254.33.7"}
s.DEV_IP.update(devs)
assert s.guess_via("10.0.0.5", nets, "en7") == "169.254.33.7"       # placa do IP_RECVIF
assert s.guess_via("192.168.0.80", nets) == "192.168.0.20"          # sem IP_RECVIF: pela faixa
assert s.guess_via("10.0.0.5", nets) == ""                          # duas placas, nenhuma na faixa
assert s.guess_via("10.0.0.5", {"192.168.0.20": nets["192.168.0.20"]}) == "192.168.0.20"  # placa única

class Racy(dict):  # DEV_IP limpo por mac_networks() entre o `in` e o `[]`
    def __contains__(self, k):
        return True

    def __getitem__(self, k):
        raise KeyError(k)
s.DEV_IP, dev_ip = Racy(), s.DEV_IP
assert s.guess_via("192.168.0.80", nets, "en0") == "192.168.0.20"   # sem KeyError na thread do listen
s.DEV_IP = dev_ip

# LAN hostil: enxurrada de broadcasts / MACs forjados (sem Tk: App com stubs)
import queue, socket, threading
from types import SimpleNamespace as NS
noop = lambda *a, **k: None

ran = []
def again():  # callable que reenfileira: o drain antigo nunca devolvia a UI
    ran.append(1)
    if len(ran) < 1000:
        app.ui.put(again)
app = NS(root=NS(after=noop), drain=noop, ui=queue.Queue())
app.ui.put(again)
s.App.drain(app)
assert len(ran) == 1

def pkt(mac):
    return bytes.fromhex(mac) + struct.pack("<HHHI", 30, 3, 3839, 180000) + bytes(20)
app = NS(ui=queue.Queue(), nets={})
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0))
th = threading.Thread(target=s.listen, args=(rx, "127.0.0.1", app), daemon=True)
th.start()
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for i in range(3 * s.QUEUE_MAX):
    tx.sendto(pkt("00000000%04x" % i), rx.getsockname())
    if i % 50 == 0:
        time.sleep(0.005)
time.sleep(0.3)
assert 0 < app.ui.qsize() <= s.QUEUE_MAX
tx.close()
rx.close()
th.join(2)
assert not th.is_alive()                                            # socket fechado: listener sai

app = NS(dacs={}, order=[], sel=None, sync_list=noop, set_log=noop, label=str)
for i in range(s.MAX_DACS + 10):
    s.App.got_packet(app, pkt("00000000%04x" % i), ("10.0.0.%d" % (i % 250), 7654), "")
assert len(app.dacs) == len(app.order) == s.MAX_DACS
s.App.got_packet(app, pkt("000000000000"), ("10.0.0.99", 7654), "")   # DAC já conhecida continua atualizando
assert app.dacs["000000000000"].bc.ip == "10.0.0.99"

# placas do PC lidas fora da thread da UI, aplicadas dentro do tick
pc_networks, seen = s.pc_networks, []
s.pc_networks = lambda: seen.append(threading.current_thread()) or NETS
app = NS(root=NS(after=noop), tick=noop, ticks=s.NET_EVERY - 1, dacs={}, nets={}, new_nets=None, refresh=noop, applied=[])
app.read_nets = lambda: s.App.read_nets(app)
app.sync_sockets = app.applied.append
s.App.tick(app)
for _i in range(200):
    if app.new_nets or app.applied:
        break
    time.sleep(0.01)
assert seen and seen[0] is not threading.main_thread()
s.App.tick(app)
assert app.applied == [NETS] and app.new_nets is None
s.pc_networks = pc_networks

s.LANG = "en"
assert s.health(dac(), now)[1] == "OPERATIONAL"
assert s._("REDE") == "NETWORK"
assert [len(n) for _t, n in s.GROUPS] == [len(v) for v in s.params(dac(), now)]  # rótulos x valores
assert s._("resposta desconhecida %r") % b"\xff" == "unknown response b'\\xff'"
s.LANG = "pt"
print("ok")
