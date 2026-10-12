#!/usr/bin/env python3
# Ether Dream Sitter — edição Feitiçaria Industrial
#
# Derivado de j4cDAC "sitter", Copyright 2012 Jacob Potter.
# Port para Python 3, redesign, status por LED e Clear E-Stop: Feitiçaria Industrial, 2026.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# Protocolo: https://ether-dream.com/protocol.html (ED2, ED3 e ED4)

import ctypes
import faulthandler
import html
import ipaddress
import json
import locale
import os
import queue
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from tkinter import font as tkfont, messagebox

BCAST_PORT, CTRL_PORT = 7654, 7765
TIMEOUT_S = 5  # sem broadcast por esse tempo = offline (a DAC anuncia 1x/s; Wi-Fi perde alguns)
RETRY_S = 5    # nova tentativa de ler o firmware
CTRL_TTL = 30  # resultado da última conexão TCP vale por esse tempo
NET_EVERY = 10  # ticks (5 s) entre releituras das placas de rede do PC
try:  # pausa do "clique lento" que renomeia, igual à do Windows
    DCLICK_MS = ctypes.windll.user32.GetDoubleClickTime()
except AttributeError:
    DCLICK_MS = 500
# ponytail: tabela fixa de ether-dream.com/downloads.html em 2026-10; atualizar à mão quando sair firmware novo
LATEST_FW = (("ed4-", 354), ("ed3v", 86), ("r", 331))

# Paleta: tokens FI + cores funcionais de LED (a identidade não define vermelho/âmbar)
BG, FG, MUTED, LINE = "#000000", "#F7F5EB", "#8A8784", "#2A2928"
CARD, SELECT = "#0D0D0C", "#1A1A18"
OK, BUSY, WARN, ERR, OFF = "#A8E05E", "#B7AED9", "#F5B83D", "#FF4D4D", "#4A4847"
CYAN = "#3FE0B8"  # verde-ciano do LED ocioso

MAC = sys.platform == "darwin"
if MAC:  # dentro do .app não se grava (assinatura e App Translocation): pastas do usuário
    APP_DIR = os.path.expanduser("~/Library/Application Support/EtherDreamSitterFI")
    LOG_DIR = os.path.expanduser("~/Library/Logs/EtherDreamSitterFI")
else:
    APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "EtherDreamSitterFI")
NAMES_FILE = os.path.join(APP_DIR, "etherdream_nomes.json")

SOURCES = {0: "rede", 1: "cartão (arquivo)", 2: "gerador interno"}

# LED RGB da ED4, sem tabela oficial. Verde-ciano, branco e E-stop: vistos na ED4 do Matheus (2026-10-12);
# os demais: fórum Liberation 2026. (cor, padrão, pisca, texto)
LED_MANUAL = [
    (CYAN, "VERDE-CIANO", False, "Ociosa."),
    (FG, "BRANCO", False, "Tocando."),
    (CYAN, "E-STOP", False, "LED não muda. Só o sitter mostra."),
    (CYAN, "PISCANDO", True, "Falha de rede → cabo / switch / IP."),
    (ERR, "VERMELHO", False, "Ver sitter. E-STOP → Limpar. Travada → desligar 1 min."),
]

LABELS_HTML = """<!doctype html><meta charset="utf-8"><title>%s</title>
<style>
@page{margin:10mm}body{margin:0;font-family:"Segoe UI",Arial,sans-serif;color:#000}
.l{display:inline-flex;flex-direction:column;justify-content:center;box-sizing:border-box;width:70mm;height:32mm;
margin:0 3mm 3mm 0;padding:3mm 5mm;border:1px dashed #000;break-inside:avoid;vertical-align:top}
b{font-size:17pt;line-height:1.1;margin-bottom:1.5mm}span{font:10pt Consolas,monospace}
i{font-style:normal;font-size:6pt;letter-spacing:.16em;color:#555;margin-top:2mm}
</style><body onload="print()">%s</body>"""

# --- idioma -----------------------------------------------------------------
LANG = "pt"
EN = {
    # estado geral
    "OCUPADA": "BUSY", "SEM CONTROLE": "NO CONTROL", "TOCANDO": "PLAYING", "PREPARADA": "PREPARED",
    "OPERACIONAL": "OPERATIONAL", "NENHUMA DAC": "NO DAC", "FAIXA ERRADA": "WRONG SUBNET",
    "IP DUPLICADO": "DUPLICATE IP",
    "sem sinal há %d s — energia, cabo ou rede": "no signal for %d s — power, cable or network",
    "laser bloqueado — ": "laser blocked — ", "causa não informada": "cause not reported",
    "interlock aberto": "interlock open", "temperatura alta": "over temperature",
    "disparado pelo interlock": "tripped by interlock", "disparado por temperatura": "tripped by temperature",
    "link Ethernet caiu": "Ethernet link lost", "comando de rede": "network command",
    "comando de software, não é falha física": "software command, not a physical fault",
    "o PC não alcança a DAC: IP em outra faixa": "the PC can't reach the DAC: IP on another subnet",
    "outra DAC na rede usa o mesmo IP": "another DAC on the network uses the same IP",
    "outro software prende a DAC": "another app holds the DAC",
    "na rede, mas a porta TCP %d não responde": "on network, but TCP port %d does not answer",
    "software transmitindo a %d pps": "app streaming at %d pps",
    "software conectado, stream não iniciou": "app connected, stream not started",
    "pronta para receber stream": "ready for stream",
    "ligue a DAC na mesma rede deste computador": "connect the DAC to this computer's network",
    # parâmetros
    "REDE": "NETWORK", "SAÍDA": "OUTPUT", "DISPOSITIVO": "DEVICE",
    "Último sinal": "Last seen", "Placa do PC": "PC adapter", "Faixa": "Subnet", "Conexão TCP": "TCP connection",
    "Temperatura": "Temperature", "Link Ethernet": "Ethernet link", "Saída": "Output",
    "Último stream": "Last stream", "Fonte": "Source", "Atualização": "Update",
    "fora · PC em %s": "outside · PC on %s",
    "livre": "free", "recusada": "refused", "sem resposta": "no answer", "não testada": "not tested",
    "falha": "failed",
    "liberado": "enabled", "liberado · flag de rede": "enabled · network flag", "E-STOP (software)": "E-STOP (software)",
    "ABERTO": "OPEN", "disparou, já fechado": "tripped, now closed", "fechado": "closed",
    "ALTA": "HIGH", "disparou, já normal": "tripped, now normal", "normal": "normal",
    "caiu durante o stream": "lost during stream",
    "tocando · %d pps": "playing · %d pps", "preparada": "prepared", "ociosa": "idle",
    "parou por E-stop": "stopped by E-stop", "underflow (software parou)": "underflow (app stopped)",
    "rede": "network", "cartão (arquivo)": "card (file)", "gerador interno": "internal generator",
    "fonte %d": "source %d", "não lido (%s)": "not read (%s)",
    "aguardando DAC parada": "waiting for idle DAC", "consultando…": "reading…",
    "(antigo, sem consulta)": "(old, not queried)", "(sem suporte a v)": "(no v support)",
    "%s disponível": "%s available", "em dia": "up to date",
    # interface
    "DACS NA REDE": "DACS ON NETWORK","Enter salva · Esc cancela": "Enter saves · Esc cancels",
    "LIMPAR E-STOP": "CLEAR E-STOP", "GUIA LED": "LED GUIDE", "GUIA IP": "IP GUIDE", "IMPRIMIR": "PRINT", "ETIQUETAS":"LABELS",
    "REDE DO PC": "PC NETWORK", "IP DA ED4": "ED4 IP",
    "DAC em %s · PC (%s) em %s": "DAC at %s · PC (%s) on %s",
    "IP %s usado por mais de uma DAC": "IP %s used by more than one DAC",
    "aguardando broadcast na porta %d…": "waiting for broadcast on port %d…",
    "porta UDP %d indisponível ou sem rede": "UDP port %d unavailable or no network",
    "DAC %s encontrada em %s": "DAC %s found at %s", "DAC %s voltou em %s": "DAC %s back at %s",
    "selecione uma DAC": "select a DAC", "aguarde: comando em andamento": "wait: command in progress",
    "enviando Clear E-Stop para %s…": "sending Clear E-Stop to %s…",
    "falhou: DAC %s — feche o software de laser e tente de novo":
        "failed: DAC %s — close the laser app and try again",
    "A DAC pode estar tocando. Conectar agora interrompe a saída do laser na Ether Dream 4."
    "\n\nEnviar Clear E-Stop mesmo assim?":
        "The DAC may be playing. Connecting now stops the laser output on Ether Dream 4."
        "\n\nSend Clear E-Stop anyway?",
    "E-stop limpo": "E-stop cleared", "não estava em E-stop": "was not in E-stop",
    "ACK, mas continua em E-stop": "ACK, but still in E-stop",
    "NAK — a causa continua ativa (interlock ou temperatura)": "NAK — cause still active (interlock or temperature)",
    "NAK — comando inválido": "NAK — invalid command", "NAK buffer cheio": "NAK buffer full",
    "resposta desconhecida %r": "unknown response %r",
    "não consegui salvar os nomes: %s": "could not save names: %s",
    "nenhuma DAC para etiquetar": "no DAC to label", "etiquetas abertas no navegador": "labels opened in browser",
    "não consegui abrir as etiquetas: %s": "could not open labels: %s",
    "Etiquetas Ether Dream": "Ether Dream labels", "ip.txt copiado": "ip.txt copied",
    # guia do LED
    "Guia do LED — Ether Dream": "LED guide — Ether Dream",
    "VERDE-CIANO": "GREEN-CYAN", "BRANCO": "WHITE", "PISCANDO": "BLINKING", "VERMELHO": "RED",
    "Ociosa.": "Idle.", "Tocando.": "Playing.", "LED não muda. Só o sitter mostra.": "LED doesn't change. Only the sitter shows it.",
    "Falha de rede → cabo / switch / IP.": "Network fault → cable / switch / IP.",
    "Ver sitter. E-STOP → Limpar. Travada → desligar 1 min.": "Check sitter. E-STOP → Clear. Frozen → power off 1 min.",
    # guia de IP
    "Guia de IP — Ether Dream": "IP guide — Ether Dream",
    "MUDAR O PC": "CHANGE THE PC", "mais rápido": "fastest",
    "REDE DO PC → placa → Propriedades → IPv4": "PC NETWORK → adapter → Properties → IPv4",
    "REDE DO PC → placa → Detalhes → TCP/IP → Manualmente": "PC NETWORK → adapter → Details → TCP/IP → Manually",
    "IP fixo na faixa da DAC:": "Static IP on the DAC's subnet:",
    "MUDAR A ED4": "CHANGE THE ED4",
    "USB-C de dados no PC → a ED4 abre como pendrive": "Data USB-C to the PC → the ED4 mounts as a drive",
    "Criar ip.txt na raiz (valores para a rede deste PC):": "Create ip.txt at the root (values for this PC's network):",
    "COPIAR": "COPY", "Ejetar e religar a DAC": "Eject and power-cycle the DAC",
    "Voltar ao DHCP: apagar ip.txt": "Back to DHCP: delete ip.txt",
    "Sem DHCP, DAC e PC usam 169.254.x.x e se acham sozinhos.":
        "Without DHCP, DAC and PC use 169.254.x.x and find each other.",
}


def _(text):
    return EN.get(text, text) if LANG == "en" else text


def system_lang():
    """'pt' se o sistema estiver em português, senão 'en'."""
    try:
        return "pt" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x16 else "en"
    except AttributeError:
        pass
    if MAC:  # app aberto pelo Finder não herda LANG: idioma vem das preferências do macOS
        try:
            out = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
                                 capture_output=True, text=True, timeout=3).stdout
            return "pt" if re.search(r"\w+", out.replace("(", "")).group().lower() == "pt" else "en"
        except (OSError, AttributeError, subprocess.SubprocessError):
            pass
    return "pt" if (locale.getlocale()[0] or "").lower().startswith("pt") else "en"


def log_error(text):
    """Grava erro em %LOCALAPPDATA%\\EtherDreamSitterFI\\erro.log (o .exe windowed não tem console)."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "erro.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except OSError:
        pass


# --- protocolo --------------------------------------------------------------
class Status:
    """struct dac_status (20 bytes)."""
    def __init__(self, data):
        (self.protocol, self.le_state, self.playback_state, self.source,
         self.le_flags, self.playback_flags, self.source_flags,
         self.fullness, self.point_rate, self.point_count) = struct.unpack("<BBBBHHHHII", data)


class Broadcast:
    """Pacote UDP de anúncio (36 bytes). via = IP da placa do PC que recebeu."""
    def __init__(self, data, addr, via=""):
        self.mac = data[:6].hex()
        self.hw_rev, self.sw_rev, self.buffer_capacity, self.max_point_rate = \
            struct.unpack("<HHHI", data[6:16])
        self.status = Status(data[16:36])
        self.ip = addr[0]
        self.via = via
        self.time = time.time()


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("DAC closed the connection")
        buf += chunk
    return buf


def clear_result(hello, resp):
    """Resposta do Clear E-Stop → (texto, arg). A ED4 dá ACK mesmo sem E-stop,
    então compara o le_state (byte 3) do hello com o da resposta."""
    code = resp[0:1]
    if code == b"a":
        if hello[3] != 3:
            return "não estava em E-stop", None
        return ("ACK, mas continua em E-stop", None) if resp[3] == 3 else ("E-stop limpo", None)
    if code == b"!":
        return "NAK — a causa continua ativa (interlock ou temperatura)", None
    if code == b"I":
        return "NAK — comando inválido", None
    if code == b"F":
        return "NAK buffer cheio", None
    return "resposta desconhecida %r", code


def dac_command(ip, cmd=None):
    """Conecta na porta de controle, envia cmd (None = só testa) e desconecta.

    ATENÇÃO: na ED4 (ed4-152) uma conexão nova interrompe o stream em andamento
    (testado em 2026-10-12). Só chamar com a DAC parada ou por clique do usuário.
    A ED2/ED3 aceita um host por vez e recusa os demais.
    """
    with socket.create_connection((ip, CTRL_PORT), timeout=1) as conn:
        hello = recv_exact(conn, 22)  # boas-vindas: 'a', '?', status
        if cmd is None:
            return "livre"
        conn.sendall(cmd)
        resp = recv_exact(conn, 22)
        if cmd == b"v":
            if resp[0:1] in (b"I", b"!", b"F") and resp[1:2] == b"v":  # firmware sem o comando v
                return "(sem suporte a v)"
            resp += recv_exact(conn, 10)  # versão: 32 bytes
            return resp.replace(b"\0", b" ").decode("ascii", "replace").strip()
        return clear_result(hello, resp)


# --- rede do PC -------------------------------------------------------------
def pc_networks():
    """{ip local: (máscara, nome da placa)} das placas IPv4 ativas (iphlpapi do Windows)."""
    try:
        iph = ctypes.windll.iphlpapi
    except AttributeError:
        return mac_networks()
    size = ctypes.c_ulong(0)
    iph.GetIpAddrTable(None, ctypes.byref(size), False)
    buf = ctypes.create_string_buffer(max(size.value, 4))
    if iph.GetIpAddrTable(buf, ctypes.byref(size), False):
        return {}
    nets = {}
    for i in range(struct.unpack_from("<I", buf)[0]):
        addr, index, mask, bcast, reasm, unused, kind = struct.unpack_from("<IIIIIHH", buf, 4 + 24 * i)
        if kind & 0x48:  # MIB_IPADDR_DISCONNECTED | MIB_IPADDR_DELETED
            continue
        luid, alias = ctypes.c_uint64(), ctypes.create_unicode_buffer(257)
        named = (iph.ConvertInterfaceIndexToLuid(index, ctypes.byref(luid)) == 0
                 and iph.ConvertInterfaceLuidToAlias(ctypes.byref(luid), alias, 257) == 0)
        nets[socket.inet_ntoa(struct.pack("<I", addr))] = (socket.inet_ntoa(struct.pack("<I", mask)),
                                                           alias.value if named else "")
    return nets


DEV_IP = {}  # macOS: placa (en0) -> IP, para saber por onde chegou cada broadcast
IP_RECVIF = 20  # macOS <netinet/in.h>: pacote traz a placa que o recebeu (o módulo socket não exporta)


def parse_ifconfig(ifconfig, ports=""):
    """Saídas de `ifconfig` e `networksetup -listallhardwareports` -> ({ip: (máscara, nome)}, {placa: ip})."""
    names = dict((dev, port) for port, dev in re.findall(r"Hardware Port: (.+)\nDevice: (\S+)", ports))
    nets, dev_ip, dev = {}, {}, None
    for line in ifconfig.splitlines():
        m = re.match(r"(\w+): flags=", line)
        if m:
            dev = m.group(1)
        m = re.match(r"\s+inet (\S+) netmask 0x([0-9a-f]{8})", line)
        if m and dev and not m.group(1).startswith("127."):
            nets[m.group(1)] = (socket.inet_ntoa(bytes.fromhex(m.group(2))), names.get(dev, dev))
            dev_ip.setdefault(dev, m.group(1))
    return nets, dev_ip


def mac_networks():
    def run(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    nets, dev_ip = parse_ifconfig(run("/sbin/ifconfig"), run("/usr/sbin/networksetup", "-listallhardwareports"))
    DEV_IP.clear()
    DEV_IP.update(dev_ip)
    return nets


def guess_via(dac_ip, nets, dev=None):
    """macOS (um socket só): placa que recebeu = a do IP_RECVIF; senão a que tem a DAC na faixa;
    senão a única placa ativa; senão desconhecida."""
    if dev in DEV_IP:
        return DEV_IP[dev]
    for ip, (mask, _name) in nets.items():
        if ipaddress.ip_address(dac_ip) in subnet(ip, mask):
            return ip
    return next(iter(nets)) if len(nets) == 1 else ""


def subnet(ip, mask):
    return ipaddress.ip_interface("%s/%s" % (ip, mask)).network


def net_issue(dac, dacs, nets, now):
    """'faixa' (DAC fora da rede da placa que a recebe), 'duplicado' (mesmo IP em outra DAC online) ou None."""
    iface = nets.get(dac.bc.via)
    if iface and ipaddress.ip_address(dac.bc.ip) not in subnet(dac.bc.via, iface[0]):
        return "faixa"
    if any(o is not dac and o.bc.ip == dac.bc.ip and now - o.bc.time <= TIMEOUT_S for o in dacs):
        return "duplicado"
    return None


def suggest_ip(pc_ip, mask, used):
    """(ip, máscara, gateway) livres para a DAC na rede da placa do PC, a partir do host .50."""
    net = subnet(pc_ip, mask)
    for k in range(50, net.num_addresses - 1):
        ip = str(net.network_address + k)
        if ip != pc_ip and ip not in used:
            return ip, mask, str(net.network_address + 1)
    return None


def suggest_pc_ip(dac_ip):
    # ponytail: assume /24, o caso de rede de show; o guia mostra a máscara junto
    base, last = dac_ip.rsplit(".", 1)
    return "%s.%d" % (base, 11 if last == "10" else 10)


def mac_text(mac):
    return ":".join(mac[i:i + 2] for i in range(0, 12, 2))


# --- leitura do estado (textos em PT; traduzidos por _()) -------------------
class Dac:
    def __init__(self, bc):
        self.bc = bc
        self.firmware = None        # None = ainda não lido
        self.ctrl = "não testada"   # livre | recusada | sem resposta | falha (última conexão)
        self.ctrl_time = 0
        self.next_try = 0
        self.busy = False           # há thread de rede em andamento
        self.net = None             # None | 'faixa' | 'duplicado'
        self.idle_streak = 0        # broadcasts seguidos com playback parado


def fw_update(fw):
    """Versão mais nova conhecida se fw estiver desatualizado, senão None."""
    for prefix, latest in LATEST_FW:
        m = re.match(re.escape(prefix) + r"(\d+)", fw)
        if m:
            return "%s%d" % (prefix, latest) if int(m.group(1)) < latest else None
    return None


def net_flag_only(st):
    """E-stop só com o flag 'comando de rede'. Na ED4 o MadMapper deixa isso ligado e o stream
    segue tocando (visto em 2026-10-12): não é falha física."""
    return st.le_state == 3 and st.le_flags == 1


def health(dac, now):
    """LED geral: (cor, título, motivo), já traduzidos."""
    age = now - dac.bc.time
    if age > TIMEOUT_S:
        return OFF, "OFFLINE", _("sem sinal há %d s — energia, cabo ou rede") % age
    st = dac.bc.status
    if st.le_state == 3 and not net_flag_only(st):
        causes = [_(t) for bit, t in ((2, "interlock aberto"), (4, "temperatura alta"),
                                      (1, "disparado pelo interlock"), (3, "disparado por temperatura"),
                                      (5, "link Ethernet caiu"), (0, "comando de rede"))
                  if st.le_flags >> bit & 1]
        return ERR, "E-STOP", _("laser bloqueado — ") + (", ".join(causes) or _("causa não informada"))
    if net_flag_only(st) and st.playback_state != 2:
        return WARN, "E-STOP", _("comando de software, não é falha física")
    if dac.net == "faixa":
        return WARN, _("FAIXA ERRADA"), _("o PC não alcança a DAC: IP em outra faixa")
    if dac.net == "duplicado":
        return WARN, _("IP DUPLICADO"), _("outra DAC na rede usa o mesmo IP")
    if st.playback_state == 0 and now - dac.ctrl_time < CTRL_TTL:
        if dac.ctrl == "recusada":
            return WARN, _("OCUPADA"), _("outro software prende a DAC")
        if dac.ctrl == "sem resposta":
            return WARN, _("SEM CONTROLE"), _("na rede, mas a porta TCP %d não responde") % CTRL_PORT
    if st.playback_state == 2:
        return BUSY, _("TOCANDO"), _("software transmitindo a %d pps") % st.point_rate
    if st.playback_state == 1:
        return BUSY, _("PREPARADA"), _("software conectado, stream não iniciou")
    return OK, _("OPERACIONAL"), _("pronta para receber stream")


# cards da tela: (título, rótulos); params() devolve os valores na mesma ordem
GROUPS = (("REDE", ("IP", "Último sinal", "Placa do PC", "Faixa", "Conexão TCP")),
          ("LASER", ("Laser", "Interlock", "Temperatura", "Link Ethernet")),
          ("SAÍDA", ("Saída", "Buffer", "Último stream", "Fonte")),
          ("DISPOSITIVO", ("Firmware", "Atualização", "Hardware", "MAC")))


def params(dac, now, nets=None):
    """Valores [[(valor, cor do LED)] por card de GROUPS], já traduzidos."""
    bc, st = dac.bc, dac.bc.status
    age = now - bc.time
    f = st.le_flags
    pct = 100 * st.fullness // max(bc.buffer_capacity, 1)

    iface = (nets or {}).get(bc.via)
    if iface:
        place = ((iface[1] + " · ") if iface[1] else "") + bc.via
        net = subnet(bc.via, iface[0])
        rng = (_("fora · PC em %s") % net, WARN) if dac.net == "faixa" else ("ok · %s" % net, OK)
    else:
        place, rng = "—", ("—", OFF)

    fresh = now - dac.ctrl_time < CTRL_TTL
    ctrl_color = {"livre": OK, "recusada": WARN, "sem resposta": WARN, "falha": WARN}.get(dac.ctrl, OFF)
    if dac.firmware:
        fw = _(dac.firmware)
    elif dac.ctrl not in ("não testada", "livre"):
        fw = _("não lido (%s)") % _(dac.ctrl)
    else:
        fw = "—" if dac.net else _("aguardando DAC parada") if st.playback_state else _("consultando…")
    upd = fw_update(dac.firmware or "")

    if net_flag_only(st):
        laser = ("liberado · flag de rede", OK) if st.playback_state == 2 else ("E-STOP (software)", WARN)
    else:
        laser = ("E-STOP", ERR) if st.le_state == 3 else ("liberado", OK)
    if st.playback_state == 2:
        out = (_("tocando · %d pps") % st.point_rate, BUSY)
    elif st.playback_state == 1:
        out = (_("preparada"), BUSY)
    else:
        out = (_("ociosa"), OFF)
    last = ("parou por E-stop", WARN) if st.playback_flags & 4 else \
           ("underflow (software parou)", OFF) if st.playback_flags & 2 else ("normal", OFF)

    return [
        [
            (bc.ip, WARN if dac.net == "duplicado" else OK),
            ("%.1f s" % age, OK if age < 2.5 else WARN if age <= TIMEOUT_S else ERR),
            (place, OK if iface else OFF),
            rng,
            (_(dac.ctrl), ctrl_color if fresh else OFF),
        ],
        [
            (_(laser[0]), laser[1]),
            (_("ABERTO" if f & 4 else ("disparou, já fechado" if f & 2 else "fechado")),
             ERR if f & 4 else (WARN if f & 2 else OK)),
            (_("ALTA" if f & 16 else ("disparou, já normal" if f & 8 else "normal")),
             ERR if f & 16 else (WARN if f & 8 else OK)),
            (_("caiu durante o stream" if f & 32 else "ok"), WARN if f & 32 else OK),
        ],
        [
            (out[0], out[1]),
            ("%d / %d · %d%%" % (st.fullness, bc.buffer_capacity, pct), OFF),
            (_(last[0]), last[1]),
            (_(SOURCES[st.source]) if st.source in SOURCES else _("fonte %d") % st.source, OFF),
        ],
        [
            (fw, OK if dac.firmware else OFF),
            (_("%s disponível") % upd if upd else (_("em dia") if dac.firmware else "—"),
             WARN if upd else (OK if dac.firmware else OFF)),
            ("hw %d · sw %d" % (bc.hw_rev, bc.sw_rev), OFF),
            (mac_text(bc.mac), OFF),
        ],
    ]


def load_names():
    try:
        with open(NAMES_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_names(names):
    """None se salvou, senão a mensagem de erro."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(NAMES_FILE, "w", encoding="utf-8") as fh:
            json.dump(names, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError as e:
        return e.strerror or str(e)
    return None


def open_path(*args):
    """Abre arquivo ou painel com o programa padrão do sistema (args extras: só `open` do macOS)."""
    if MAC:
        subprocess.Popen(["/usr/bin/open", *args])
    else:
        os.startfile(args[-1])


def open_adapters():
    try:  # Conexões de Rede do Windows / Ajustes do Sistema → Rede
        if MAC:
            open_path("-b", "com.apple.systempreferences", "/System/Library/PreferencePanes/Network.prefPane")
        else:
            open_path("ncpa.cpl")
    except OSError as e:
        log_error("rede do PC: %s" % e)


# --- interface --------------------------------------------------------------
def pick_font(root, names, size, weight="normal"):
    available = set(tkfont.families(root))
    if MAC:  # Tk no macOS mede ponto a 72 dpi (Windows: 96): sem isso tudo sai 25% menor
        names, size = names + ["Menlo" if "Consolas" in names else "Helvetica Neue"], round(size * 4 / 3)
    return (next((n for n in names if n in available), names[-1]), size, weight)


def dark_titlebar(win):
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
    except (AttributeError, OSError):
        pass


def dim(color, k=0.3):
    """Mistura a cor com o preto (halo do LED)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * k), int(g * k), int(b * k))


class Led(tk.Canvas):
    """LED com halo."""
    def __init__(self, master, size, bg=BG):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0)
        self.bg, self.color = bg, OFF
        p = size // 5
        self.halo = self.create_oval(0, 0, size, size, outline="", fill=bg)
        self.core = self.create_oval(p, p, size - p, size - p, outline="", fill=OFF)

    def set(self, color, bg=None):
        if bg and bg != self.bg:
            self.bg = bg
            self.config(bg=bg)
        self.color = color
        self.itemconfig(self.core, fill=color)
        self.itemconfig(self.halo, fill=dim(color) if color not in (OFF, self.bg) else self.bg)


def button(parent, text, cmd, font, primary=True):
    bg, fg, edge = (OK, BG, OK) if primary else (BG, FG, LINE)
    # contorno num Frame: no macOS o Label não desenha highlight
    box = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=edge)
    b = tk.Label(box, text=text, font=font, padx=14, pady=7, cursor="hand2", bg=bg, fg=fg)
    b.pack()
    for w in (box, b):
        w.bind("<Button-1>", lambda e: cmd())
        w.bind("<Enter>", lambda e: box.config(highlightbackground=FG))
        w.bind("<Leave>", lambda e: box.config(highlightbackground=edge))
    box.paint = lambda bg, fg: (box.config(bg=bg), b.config(bg=bg, fg=fg))
    return box


class App:
    def __init__(self, root):
        self.root = root
        self.ui = queue.Queue()  # callables vindos das threads de rede
        self.dacs = {}           # mac -> Dac
        self.order = []          # macs na ordem em que apareceram
        self.sel = None          # mac selecionado
        self.nets = {}           # ip local -> (máscara, placa)
        self.socks = {}          # ip local -> socket UDP
        self.names = load_names()
        self.ticks = 0
        self.wins = {}           # janela de ajuda aberta por tipo (no máximo uma de cada)

        self.f_body = pick_font(root, ["Inter", "Segoe UI"], 10)
        self.f_bold = pick_font(root, ["Inter", "Segoe UI"], 10, "bold")
        self.f_small = pick_font(root, ["Inter", "Segoe UI"], 9)
        self.f_mono = pick_font(root, ["JetBrains Mono", "Consolas"], 10)
        self.f_caps = pick_font(root, ["Inter", "Segoe UI"], 8, "bold")
        self.f_name = pick_font(root, ["Inter", "Segoe UI"], 14, "bold")
        self.f_big = pick_font(root, ["Inter", "Segoe UI"], 24, "bold")
        self.logo = tk.PhotoImage(data=LOGOMARK_B64)
        if root.winfo_fpixels("1i") < 120:  # telas 100–125%: metade do tamanho
            self.logo = self.logo.subsample(2)

        root.title("Ether Dream Sitter — Feitiçaria Industrial")
        root.configure(bg=BG)
        self.sync_sockets()
        self.build()
        # tamanho único: calculado uma vez para o pior caso (aviso de rede e todas as linhas
        # reservados); depois o texto não mexe mais na janela, só o usuário redimensiona
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry("%dx%d" % (w, h))
        root.minsize(w, h)
        root.bind_all("<MouseWheel>", self.wheel)
        root.bind("<F2>", lambda e: self.rename())  # F2 renomeia, como no Explorer
        if self.socks:
            self.set_log(_("aguardando broadcast na porta %d…") % BCAST_PORT)
        else:
            self.set_log(_("porta UDP %d indisponível ou sem rede") % BCAST_PORT, alert=True)
        root.after(100, self.drain)
        root.after(500, self.tick)

    def build(self):
        """Monta a tela no idioma atual (refeita ao trocar de idioma)."""
        root = self.root
        self.items, self.editing, self.banner_shown, self.pending, self.hot = {}, None, None, None, None

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=28, pady=(18, 16))
        tk.Label(head, image=self.logo, bg=BG).pack(side="left")
        toggle = tk.Frame(head, bg=BG, highlightthickness=1, highlightbackground=MUTED)
        toggle.pack(side="right")
        for code in ("PT", "EN"):
            on = LANG == code.lower()
            lab = tk.Label(toggle, text=code, font=self.f_caps, padx=10, pady=4, cursor="hand2",
                           bg=FG if on else BG, fg=BG if on else MUTED)
            lab.pack(side="left")
            lab.bind("<Button-1>", lambda e, c=code.lower(): self.set_lang(c))
        tk.Label(head, text="ETHER DREAM SITTER", font=self.f_caps, bg=BG, fg=MUTED).pack(side="right", padx=(0, 20))
        tk.Frame(root, bg=LINE, height=1).pack(fill="x")

        foot = tk.Frame(root, bg=BG)
        foot.pack(side="bottom", fill="x", padx=28, pady=16)
        tk.Frame(root, bg=LINE, height=1).pack(side="bottom", fill="x")
        button(foot, _("LIMPAR E-STOP"), self.clear_estop, self.f_caps).pack(side="left")
        self.toggles = {}  # botão do rodapé de cada janela de ajuda, aceso enquanto ela está aberta
        for key, text, cmd in (("led", _("GUIA LED"), self.show_led_guide), ("ip", _("GUIA IP"), self.show_ip_guide),
                               ("labels", _("ETIQUETAS"), self.show_labels)):
            self.toggles[key] = button(foot, text, cmd, self.f_caps, primary=False)
            self.toggles[key].pack(side="left", padx=(10, 0))
            self.mark(key, key in self.wins and self.wins[key].winfo_exists())
        self.log = tk.Label(foot, font=self.f_small, bg=BG, fg=MUTED, anchor="e")
        self.log.pack(side="right")

        main = tk.Frame(root, bg=BG)
        main.pack(fill="both", expand=True, padx=28, pady=24)
        main.columnconfigure(2, weight=1)
        main.rowconfigure(0, weight=1)

        # lista com rolagem (roda do mouse), largura fixa
        self.left = left = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="ns")
        self.count = tk.Label(left, font=self.f_caps, bg=BG, fg=MUTED, anchor="w")
        self.count.pack(fill="x", pady=(0, 10))
        list_w = tkfont.Font(root, font=self.f_bold).measure("0") * 22 + 100  # nome + LED + lápis
        self.list_canvas = tk.Canvas(left, bg=BG, highlightthickness=0, width=list_w, height=1)
        self.list_canvas.pack(fill="y", expand=True)
        self.list = tk.Frame(self.list_canvas, bg=BG)
        win_id = self.list_canvas.create_window(0, 0, window=self.list, anchor="nw", width=list_w)
        self.list.bind("<Configure>", lambda e: self.list_canvas.config(scrollregion=self.list_canvas.bbox(win_id)))
        tk.Frame(main, bg=LINE, width=1).grid(row=0, column=1, sticky="ns", padx=28)

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=2, sticky="nsew")

        hero = tk.Frame(right, bg=BG)
        hero.pack(fill="x")
        self.big_led = Led(hero, 56)
        self.big_led.pack(side="left", anchor="n", padx=(0, 20), pady=6)
        txt = tk.Frame(hero, bg=BG)
        txt.pack(side="left", fill="x")
        self.name_line = tk.Frame(txt, bg=BG)
        self.name_line.pack(anchor="w")
        self.name = tk.Label(self.name_line, font=self.f_name, bg=BG, fg=FG, cursor="xterm")
        self.name.pack(side="left")
        self.pencil = tk.Label(self.name_line, text="✎", font=self.f_name, bg=BG, fg=BG, cursor="hand2")
        self.pencil.pack(side="left", padx=10)
        self.addr = tk.Label(self.name_line, font=self.f_mono, bg=BG, fg=MUTED)
        self.addr.pack(side="left", padx=(6, 0))
        self.pencil.bind("<Button-1>", lambda e: self.rename())
        self.slow_click(self.name, lambda: self.sel, lambda: self.rename())
        self.hover(self.name_line, (self.name, self.pencil), self.pencil, lambda: BG)
        self.state = tk.Label(txt, font=self.f_big, bg=BG, fg=OFF)
        self.state.pack(anchor="w")
        self.reason = tk.Label(txt, font=self.f_body, bg=BG, fg=MUTED, anchor="w")
        self.reason.pack(anchor="w")

        # faixa do aviso de rede: espaço sempre reservado, o layout não pula quando ele aparece
        slot = tk.Frame(right, bg=BG)
        slot.pack(fill="x", pady=(20, 0))
        slot.pack_propagate(False)
        self.banner = tk.Frame(slot, bg=BG, highlightthickness=1, highlightbackground=WARN)
        self.banner_text = tk.Label(self.banner, font=self.f_body, bg=BG, fg=WARN, anchor="w")
        self.banner_text.pack(side="left", padx=16, pady=12)
        self.banner_ip = button(self.banner, _("IP DA ED4"), self.show_ip_guide, self.f_caps, primary=False)
        self.banner_ip.pack(side="right", padx=(0, 12))
        self.banner_pc = button(self.banner, _("REDE DO PC"), open_adapters, self.f_caps, primary=False)
        self.banner_pc.pack(side="right", padx=(0, 8))
        root.update_idletasks()
        slot.config(height=self.banner.winfo_reqheight())

        cards = tk.Frame(right, bg=BG)
        cards.pack(fill="both", expand=True, pady=(20, 0))
        cards.columnconfigure((0, 1), uniform="c", weight=1)
        self.card_w = []  # linhas [(led, valor)] de cada card, na ordem de GROUPS
        for i, (title, labels) in enumerate(GROUPS):
            card = tk.Frame(cards, bg=CARD, highlightthickness=1, highlightbackground=LINE)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0, 14) if i % 2 == 0 else 0, pady=(0, 14))
            tk.Label(card, text=_(title), font=self.f_caps, bg=CARD, fg=MUTED, anchor="w").grid(
                row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 8))
            rows = []
            for r, name in enumerate(labels, start=1):
                led = Led(card, 10, CARD)
                led.grid(row=r, column=0, padx=(18, 12), pady=4)
                tk.Label(card, text=_(name).upper(), font=self.f_caps, bg=CARD, fg=MUTED, width=15,
                         anchor="w").grid(row=r, column=1, sticky="w")
                val = tk.Label(card, font=self.f_body, bg=CARD, fg=FG, anchor="w", width=24)
                val.grid(row=r, column=2, sticky="w", padx=(0, 18))
                rows.append((led, val))
            tk.Frame(card, bg=CARD, height=12).grid(row=99, column=0)
            self.card_w.append(rows)
        self.sync_list()
        self.refresh()

    def set_lang(self, lang):
        global LANG
        if lang == LANG:
            return
        LANG = lang
        self.end_rename(True)
        if self.pending:
            self.root.after_cancel(self.pending)
        for w in self.root.winfo_children():  # inclui as janelas de guia, se abertas
            w.destroy()
        self.build()

    # --- dados -------------------------------------------------------------
    def sync_sockets(self):
        """Windows: um socket UDP por placa IPv4, assim cada broadcast diz por qual placa chegou.
        macOS: socket preso a IP de placa não recebe broadcast; um socket só (via=None) e a placa
        vem de cada pacote (guess_via)."""
        self.nets = pc_networks()
        for ip in [ip for ip in self.socks if ip not in self.nets and ip != ""]:
            self.socks.pop(ip).close()
        for ip in [""] if MAC else self.nets:
            if ip in self.socks:
                continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # convive com MadMapper/LSX
            if MAC:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                try:
                    sock.setsockopt(socket.IPPROTO_IP, IP_RECVIF, 1)
                except OSError:
                    pass
            try:
                sock.bind((ip, BCAST_PORT))
            except OSError:
                sock.close()
                continue
            self.socks[ip] = sock
            threading.Thread(target=listen, args=(sock, None if MAC else ip, self), daemon=True).start()

    def got_packet(self, data, addr, via):
        bc = Broadcast(data, addr, via)
        dac = self.dacs.get(bc.mac)
        if dac is None:
            dac = self.dacs[bc.mac] = Dac(bc)
            self.order.append(bc.mac)
            self.sel = self.sel or bc.mac
            self.sync_list()
            self.set_log(_("DAC %s encontrada em %s") % (self.label(bc.mac), bc.ip))
        elif bc.time - dac.bc.time > TIMEOUT_S:  # voltou (pode ter trocado firmware/IP): relê
            dac.firmware, dac.ctrl, dac.next_try, dac.idle_streak = None, "não testada", 0, 0
            self.set_log(_("DAC %s voltou em %s") % (self.label(bc.mac), bc.ip))
        dac.idle_streak = dac.idle_streak + 1 if bc.status.playback_state == 0 else 0
        dac.bc = bc

    def tick(self):
        """1x a cada 0,5 s. O estado vem só do broadcast (passivo); a única conexão
        automática é ler o firmware, e só com a DAC comprovadamente parada."""
        self.root.after(500, self.tick)  # antes de tudo: um erro aqui não para o relógio
        self.ticks += 1
        if self.ticks % NET_EVERY == 0:
            self.sync_sockets()
        now = time.time()
        dacs = list(self.dacs.values())
        for dac in dacs:
            dac.net = net_issue(dac, dacs, self.nets, now)
        for dac in dacs:
            if (dac.firmware is not None or dac.busy or now < dac.next_try or dac.net
                    or now - dac.bc.time > 1.5 or dac.idle_streak < 2):
                continue
            dac.next_try = now + RETRY_S
            if dac.bc.sw_rev < 2:
                dac.firmware = "(antigo, sem consulta)"
            else:
                self.run(dac, b"v", self.got_firmware)
        self.refresh()

    def got_firmware(self, dac, result, error):
        dac.firmware = result  # None em erro: tenta de novo depois

    def label(self, mac):
        return self.names.get(mac) or mac[6:].upper()

    def select(self, mac):
        if self.editing:
            self.end_rename(True)
        self.sel = mac
        self.refresh()

    # --- nome por DAC ------------------------------------------------------
    def slow_click(self, lab, mac_of, start):
        """Clique no nome da DAC já selecionada + pausa = renomear (mecânica do Explorer).
        Duplo clique cancela."""
        def click(e):
            if self.pending:
                self.root.after_cancel(self.pending)
            was = mac_of() == self.sel and not self.editing
            self.pending = self.root.after(DCLICK_MS, start) if was else None
            return None if was else self.select(mac_of())

        def double(e):
            if self.pending:
                self.root.after_cancel(self.pending)
                self.pending = None
        lab.bind("<Button-1>", click)
        lab.bind("<Double-Button-1>", double)

    def hover(self, area, widgets, pencil, bg_of):
        """Lápis visível só com o mouse em cima (cor do fundo = invisível, sem pular layout)."""
        def show(on, color=MUTED):
            self.hot = pencil if on else None  # refresh() respeita o hover
            pencil.config(fg=color if on else bg_of())
        for w in (area,) + tuple(widgets):
            w.bind("<Enter>", lambda e: show(True), add="+")
            w.bind("<Leave>", lambda e: show(False), add="+")
        pencil.bind("<Enter>", lambda e: show(True, FG), add="+")

    def rename(self, mac=None, lab=None):
        """Edita o nome no próprio lugar (lista ou título)."""
        mac, lab = mac or self.sel, lab or self.name
        self.pending = None
        if not mac or self.editing:
            return
        opts = {k: v for k, v in lab.pack_info().items() if k in ("side", "anchor", "padx", "pady")}
        entry = tk.Entry(lab.master, font=lab.cget("font"), width=int(lab.cget("width")) or 18, bg=CARD, fg=FG,
                         insertbackground=FG, relief="flat", highlightthickness=1, highlightbackground=LINE,
                         highlightcolor=FG)
        entry.insert(0, self.names.get(mac, ""))
        entry.select_range(0, "end")
        entry.pack(before=lab, **opts)
        lab.pack_forget()
        self.editing = (entry, mac, lab, opts)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self.end_rename(True))
        entry.bind("<Escape>", lambda e: self.end_rename(False))
        entry.bind("<FocusOut>", lambda e: self.end_rename(True))
        self.set_log(_("Enter salva · Esc cancela"))

    def end_rename(self, save):
        if not self.editing:
            return
        (entry, mac, lab, opts), self.editing = self.editing, None
        self.set_log("")
        if save:
            text = entry.get().strip()[:24]
            if text:
                self.names[mac] = text
            else:
                self.names.pop(mac, None)
            err = save_names(self.names)
            if err:
                self.set_log(_("não consegui salvar os nomes: %s") % err, alert=True)
        lab.pack(before=entry, **opts)
        entry.destroy()
        self.refresh()

    # --- tela --------------------------------------------------------------
    def sync_list(self):
        """Cria as linhas da lista para DACs novas."""
        for mac in self.order:
            if mac in self.items:
                continue
            row = tk.Frame(self.list, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=(0, 2))
            bar = tk.Frame(row, bg=BG, width=3)
            bar.pack(side="left", fill="y")
            led = Led(row, 14)
            led.pack(side="left", padx=14)
            txt = tk.Frame(row, bg=BG)
            txt.pack(side="left", pady=9)
            pencil = tk.Label(row, text="✎", font=self.f_bold, bg=BG, fg=BG, cursor="hand2")
            pencil.pack(side="right", padx=12)
            name = tk.Label(txt, font=self.f_bold, bg=BG, fg=FG, anchor="w", width=20)
            name.pack(anchor="w")
            sub = tk.Label(txt, font=self.f_small, bg=BG, fg=MUTED, anchor="w")
            sub.pack(anchor="w")
            for w in (row, bar, led, txt, sub):
                w.bind("<Button-1>", lambda e, m=mac: self.select(m))
            self.slow_click(name, lambda m=mac: m, lambda m=mac, n=name: self.rename(m, n))
            pencil.bind("<Button-1>", lambda e, m=mac, n=name: (self.select(m), self.rename(m, n)))
            self.hover(row, (bar, led, txt, name, sub), pencil, lambda r=row: r.cget("bg"))
            self.items[mac] = (row, bar, led, txt, name, sub, pencil)

    def wheel(self, e):
        """Roda do mouse sobre a lista: rola a lista."""
        if str(e.widget).startswith(str(self.left)) and self.list.winfo_height() > self.list_canvas.winfo_height():
            self.list_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def show_banner(self, issue, dac=None):
        if issue == "faixa":
            mask, card = self.nets[dac.bc.via]
            self.banner_text.config(text=_("DAC em %s · PC (%s) em %s") % (
                dac.bc.ip, card or dac.bc.via, subnet(dac.bc.via, mask)))
        elif issue == "duplicado":
            self.banner_text.config(text=_("IP %s usado por mais de uma DAC") % dac.bc.ip)
        if issue == self.banner_shown:
            return
        self.banner_shown = issue
        self.banner.pack_forget()
        self.banner_pc.pack_forget()
        if issue:
            if issue == "faixa":  # mudar o PC só resolve faixa errada
                self.banner_pc.pack(side="right", padx=(0, 8))
            self.banner.pack(fill="both", expand=True)

    def refresh(self):
        now = time.time()
        self.count.config(text="%s · %d" % (_("DACS NA REDE"), len(self.order)))
        for mac, (row, bar, led, txt, name, sub, pencil) in self.items.items():
            dac = self.dacs[mac]
            bg = SELECT if mac == self.sel else BG
            for w in (row, txt, name, sub, pencil):
                w.config(bg=bg)
            if pencil is not self.hot:
                pencil.config(fg=bg)
            bar.config(bg=FG if mac == self.sel else bg)
            led.set(health(dac, now)[0], bg)
            name.config(text=self.label(mac))
            # com nome dado, o fim do MAC continua visível na lista
            sub.config(text="%s · %s" % (dac.bc.ip, mac_text(mac)[9:].upper()) if mac in self.names else dac.bc.ip)

        dac = self.dacs.get(self.sel)
        if not dac:
            self.big_led.set(OFF)
            self.name.config(text="")
            self.addr.config(text="")
            self.state.config(text=_("NENHUMA DAC"), fg=OFF)
            self.reason.config(text=_("ligue a DAC na mesma rede deste computador"))
            self.show_banner(None)
            for rows in self.card_w:
                for led, val in rows:
                    led.set(CARD)
                    val.config(text="")
            return
        color, title, reason = health(dac, now)
        offline = color == OFF
        self.big_led.set(color)
        self.name.config(text=self.label(dac.bc.mac))
        self.addr.config(text="%s · %s" % (dac.bc.ip, mac_text(dac.bc.mac).upper()))
        self.state.config(text=title, fg=color)
        self.reason.config(text=reason)
        self.show_banner(None if offline else dac.net, dac)
        for rows, values in zip(self.card_w, params(dac, now, self.nets)):
            for (led, val), (v, c) in zip(rows, values):
                led.set(OFF if offline else c)
                val.config(text=v, fg=MUTED if offline else (c if c in (ERR, WARN) else FG))

    def set_log(self, text, alert=False):
        self.log.config(text=text, fg=WARN if alert else MUTED)

    def mark(self, key, on):
        b = self.toggles.get(key)
        if b and b.winfo_exists():
            b.paint(FG if on else BG, BG if on else FG)

    def popup(self, key, title, heading):
        """Janela de ajuda tipo toggle: uma por tipo; o botão de novo fecha a que está aberta."""
        old = self.wins.get(key)
        if old and old.winfo_exists():
            old.destroy()
            return None, None
        win = self.wins[key] = tk.Toplevel(self.root, bg=BG)
        win.title(title)
        win.resizable(False, False)
        self.mark(key, True)
        win.bind("<Destroy>", lambda e: e.widget is win and self.mark(key, False))
        body = tk.Frame(win, bg=BG)
        body.pack(padx=28, pady=(22, 24), anchor="w")
        tk.Label(body, text=heading, font=self.f_caps, bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 12))
        return win, body

    def show_led_guide(self):
        win, body = self.popup("led", _("Guia do LED — Ether Dream"), "LED · ETHER DREAM 4")
        if not win:
            return
        blinkers = []
        for color, pattern, blink, text in LED_MANUAL:
            row = tk.Frame(body, bg=BG)
            row.pack(anchor="w", pady=5)
            led = Led(row, 18)
            led.set(color)
            led.pack(side="left", padx=(0, 14))
            if blink:
                blinkers.append((led, color))
            tk.Label(row, text=_(pattern), font=self.f_caps, bg=BG, fg=color, width=14, anchor="w").pack(side="left")
            tk.Label(row, text=_(text), font=self.f_body, bg=BG, fg=FG, anchor="w").pack(side="left")

        def blink(on=True):
            if not win.winfo_exists():
                return
            for led, color in blinkers:
                led.set(color if on else OFF)
            win.after(400, blink, not on)
        blink()
        dark_titlebar(win)

    def show_ip_guide(self):
        win, body = self.popup("ip", _("Guia de IP — Ether Dream"), "IP · ETHER DREAM")
        if not win:
            return
        dac = self.dacs.get(self.sel)
        pc = dac.bc.via if dac and dac.bc.via in self.nets else \
            next((ip for ip in self.nets if not ip.startswith(("127.", "0."))), None)
        mask = self.nets[pc][0] if pc else "255.255.255.0"
        sugg = suggest_ip(pc, mask, {d.bc.ip for d in self.dacs.values()}) if pc else None
        ip_txt = "ip %s\nnetmask %s\ngateway %s" % (sugg or ("192.168.0.50", "255.255.255.0", "192.168.0.1"))

        def section(letter, title, note=""):
            f = tk.Frame(body, bg=BG)
            f.pack(anchor="w", pady=(10, 6))
            tk.Label(f, text=letter, font=self.f_name, bg=BG, fg=OK, width=2, anchor="w").pack(side="left")
            tk.Label(f, text=_(title), font=self.f_bold, bg=BG, fg=FG).pack(side="left")
            if note:
                tk.Label(f, text="  ·  " + _(note), font=self.f_small, bg=BG, fg=MUTED).pack(side="left")

        def step(n, text, value=None):
            f = tk.Frame(body, bg=BG)
            f.pack(anchor="w", padx=(30, 0), pady=3)
            tk.Label(f, text=n, font=self.f_caps, bg=BG, fg=MUTED, width=3, anchor="w").pack(side="left")
            tk.Label(f, text=_(text), font=self.f_body, bg=BG, fg=FG).pack(side="left")
            if value:
                tk.Label(f, text=value, font=self.f_mono, bg=BG, fg=OK).pack(side="left", padx=(10, 0))
            return f

        section("A", "MUDAR O PC", "mais rápido")
        step("1", "REDE DO PC → placa → Detalhes → TCP/IP → Manualmente" if MAC else "REDE DO PC → placa → Propriedades → IPv4")
        step("2", "IP fixo na faixa da DAC:",
             "%s · 255.255.255.0" % (suggest_pc_ip(dac.bc.ip) if dac else "192.168.0.10"))
        btn = tk.Frame(body, bg=BG)
        btn.pack(anchor="w", padx=(30, 0), pady=(8, 6))
        button(btn, _("REDE DO PC"), open_adapters, self.f_caps, primary=False).pack(side="left")

        section("B", "MUDAR A ED4")
        step("1", "USB-C de dados no PC → a ED4 abre como pendrive")
        step("2", "Criar ip.txt na raiz (valores para a rede deste PC):")
        box = tk.Frame(body, bg=BG)
        box.pack(anchor="w", padx=(30, 0), pady=6)
        tk.Label(box, text=ip_txt, font=self.f_mono, bg=CARD, fg=FG, justify="left", padx=16, pady=10,
                 highlightthickness=1, highlightbackground=LINE).pack(side="left")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(ip_txt + "\n")
            self.set_log(_("ip.txt copiado"))
        button(box, _("COPIAR"), copy, self.f_caps, primary=False).pack(side="left", padx=12, anchor="n")
        step("3", "Ejetar e religar a DAC")
        tk.Label(body, text=_("Voltar ao DHCP: apagar ip.txt"), font=self.f_small, bg=BG, fg=MUTED).pack(
            anchor="w", padx=(30, 0), pady=(10, 0))
        tk.Label(body, text=_("Sem DHCP, DAC e PC usam 169.254.x.x e se acham sozinhos."), font=self.f_small,
                 bg=BG, fg=MUTED).pack(anchor="w", padx=(30, 0))
        dark_titlebar(win)

    def show_labels(self):
        """Prévia das etiquetas (janela toggle como os guias); IMPRIMIR abre no navegador."""
        win, body = self.popup("labels", _("Etiquetas Ether Dream"), _("ETIQUETAS") + " · ETHER DREAM")
        if not win:
            return
        if not self.order:
            tk.Label(body, text=_("nenhuma DAC para etiquetar"), font=self.f_body, bg=BG, fg=MUTED).pack(anchor="w")
        grid = tk.Frame(body, bg=BG)
        grid.pack(anchor="w")
        for i, m in enumerate(self.order):
            card = tk.Frame(grid, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0, 10), pady=(0, 10))
            tk.Label(card, text=self.label(m), font=self.f_bold, bg=CARD, fg=FG, anchor="w", width=22).pack(anchor="w")
            for text in (mac_text(m), self.dacs[m].bc.ip):
                tk.Label(card, text=text, font=self.f_mono, bg=CARD, fg=MUTED, anchor="w").pack(anchor="w")
        if self.order:
            button(body, _("IMPRIMIR"), self.print_labels, self.f_caps).pack(anchor="w", pady=(10, 0))
        dark_titlebar(win)

    def print_labels(self):
        cards = "".join(
            '<div class="l"><b>%s</b><span>%s</span><span>%s</span><i>ETHER DREAM · FEITIÇARIA INDUSTRIAL</i></div>'
            % (html.escape(self.label(m)), mac_text(m), self.dacs[m].bc.ip) for m in self.order)
        path = os.path.join(tempfile.gettempdir(), "etherdream_etiquetas.html")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(LABELS_HTML % (html.escape(_("Etiquetas Ether Dream")), cards))
            open_path(path)
        except OSError as e:
            self.set_log(_("não consegui abrir as etiquetas: %s") % (e.strerror or e), alert=True)
            return
        self.set_log(_("etiquetas abertas no navegador"))

    # --- rede --------------------------------------------------------------
    def run(self, dac, cmd, on_result):
        """Executa dac_command numa thread; on_result(dac, resultado, erro) roda na UI."""
        dac.busy = True

        def work():
            result, error = None, "falha"
            try:
                result, error = dac_command(dac.bc.ip, cmd), None
            except socket.timeout:
                error = "sem resposta"
            except OSError:  # recusada, resetada ou fechada logo após conectar
                error = "recusada"
            finally:
                self.ui.put(lambda: done(result, error))

        def done(result, error):
            dac.busy = False
            dac.ctrl, dac.ctrl_time = error or "livre", time.time()
            on_result(dac, result, error)
        threading.Thread(target=work, daemon=True).start()

    def clear_estop(self):
        dac = self.dacs.get(self.sel)
        if not dac:
            self.set_log(_("selecione uma DAC"), alert=True)
            return
        if dac.busy:  # duplo clique ou leitura de firmware em curso
            self.set_log(_("aguarde: comando em andamento"), alert=True)
            return
        st = dac.bc.status
        if (time.time() - dac.bc.time > 2 or st.playback_state != 0) and not messagebox.askyesno(
                "Ether Dream Sitter", _("A DAC pode estar tocando. Conectar agora interrompe a saída do laser "
                                        "na Ether Dream 4.\n\nEnviar Clear E-Stop mesmo assim?"),
                parent=self.root):
            return
        if dac.busy:  # o tick pode ter começado uma leitura com o diálogo aberto
            self.set_log(_("aguarde: comando em andamento"), alert=True)
            return
        self.set_log(_("enviando Clear E-Stop para %s…") % dac.bc.ip)

        def done(dac, result, error):
            if error:
                self.set_log(_("falhou: DAC %s — feche o software de laser e tente de novo") % _(error), True)
                return
            key, arg = result
            self.set_log(_(key) % arg if arg is not None else _(key),
                         alert=key not in ("E-stop limpo", "não estava em E-stop"))
        self.run(dac, b"c", done)

    def drain(self):
        self.root.after(100, self.drain)  # antes de tudo: um erro num callable não para a fila
        while True:
            try:
                fn = self.ui.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                log_error(traceback.format_exc())


def recvif_dev(ancdata):
    """macOS: nome da placa (en0) no IP_RECVIF (struct sockaddr_dl: len, family, index u16)."""
    for level, kind, data in ancdata:
        if level == socket.IPPROTO_IP and kind == IP_RECVIF and len(data) >= 4:
            try:
                return socket.if_indextoname(struct.unpack_from("=H", data, 2)[0])
            except OSError:
                return None
    return None


def listen(sock, via, app):
    """via=None (macOS): a placa sai de cada pacote."""
    while True:
        try:
            if via is None:
                data, anc, _flags, addr = sock.recvmsg(65535, 256)
                got = guess_via(addr[0], app.nets, recvif_dev(anc))
            else:
                (data, addr), got = sock.recvfrom(65535), via
        except OSError:  # datagrama estranho (WinError 10040/10054) ou socket fechado
            if sock.fileno() < 0:
                return
            continue
        if len(data) == 36:  # broadcast Ether Dream; ignora o resto da porta
            app.ui.put(lambda d=data, a=addr, v=got: app.got_packet(d, a, v))


def main():
    global LANG, _fault_file
    LANG = system_lang()
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _fault_file = open(os.path.join(LOG_DIR, "falha.log"), "a")
        faulthandler.enable(_fault_file)
    except OSError:
        pass
    sys.excepthook = lambda t, v, tb: log_error("".join(traceback.format_exception(t, v, tb)))
    threading.excepthook = lambda a: log_error("".join(
        traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FI.EtherDreamSitter")
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.report_callback_exception = lambda t, v, tb: log_error("".join(traceback.format_exception(t, v, tb)))
    root.iconphoto(True, tk.PhotoImage(data=ICON_B64))
    App(root)
    dark_titlebar(root)
    root.mainloop()


ICON_B64 = "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"
LOGOMARK_B64 = "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"

if __name__ == "__main__":
    main()
