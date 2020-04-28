#!/usr/bin/env python3
#
# Домашнее задание DevNet марафон день 1
# Ammosov Pavel, 28 апреля 2020
#

from netmiko import ConnectHandler
import datetime
import os
import sys
import re

# название файла со списком роутеров и логинами/паролями
# список должен быть в таком формате:
# mgmt-addr/hostname,device_type,username,password,enable password (опционально)
# device_type - один из списка c https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py (CLASS_MAPPER_BASE)
ROUTER_LIST = "routers.txt"

# адрес сервера NTP для задачи 4
NTP_SERVER = "192.0.2.1"

# все команды задачи 4
CFG_COMMANDS = [
    "clock timezone GMT 0",
    "ntp server %s" % NTP_SERVER
    ]


def load_router_list(filename):
    # читает список устройств из файла `filename`
    device_list = list()
    device = dict()
    with open(filename, "r") as fp:
        for line in fp:
            x = line.strip()
            if (re.search("^\s*($|#)", x)):
                # skip empty/comment lines
                continue
            else:
                tmp = x.split(",")
                device_list.append({'mgmt_addr': tmp[0].strip(), 'device_type':tmp[1].strip(),
                                    'username':tmp[2].strip(), 'password': tmp[3].strip(),
                                    'secret': tmp[4].strip() if len(tmp) == 5 else None})
    return device_list

def netmiko_connect(device):
    connection = ConnectHandler(
        device_type=device['device_type'],
        host = device['mgmt_addr'],
        username = device['username'],
        password=device['password'],
        secret=device['secret']
    )
    if device['secret']:
        connection.enable()
    return connection

def fetch_running_conf(ssh_sess):
    # Задача 1: Собрать файлы конфигураций
    output = ssh_sess.send_command("show run")

    lines = output.splitlines()
    hostname = ""

    for str in lines:
        match = re.search("^(switch|host)name ([\w\-_]+)$", str)
        if match != None:
            hostname = match.group(2)
            break

    if hostname == "":
        print("!! Garbage was loaded instead of running-config", file=sys.stderr)
        return (None,None)

    # удалить ненужные строки перед самим конфигом
    output = re.sub("Building configuration...\n\n","", output)
    output = re.sub("Current configuration : \d+ bytes\n","", output)
    return (hostname, output)

def fetch_cdp(ssh_sess):
    # Задача 2: проверка CDP
    output = ssh_sess.send_command("show cdp neighbors")
    return output

def parse_cdp(show_cdp_output):
    # Задача 2: проверка CDP
    lines = show_cdp_output.splitlines()
    l = -1
    i = 1
    cdp_run = 1
    for str in lines:
        match = re.search("CDP is not enabled", str)
        if match:
            cdp_run = 0
            break
        match = re.search("Device ID\s+Local Intrfce\s+Holdtme\s+Capability\s+Platform\s+Port ID", str)
        if match:
            l = i
            break
        i += 1

    if cdp_run == 0:
        # CDP is off, so there is nothing todo
        return [0, 0]

    # show cdp nei длинные имена хостов печаетает в отдельной строке, а
    # информацию о них - в следующей. Эти манипуляции сливают всё вместе
    i = l
    for str in lines[l:]:
        match = re.search("^\s{2,}", str)
        if match:
            lines[i-1] += " " + lines[i].lstrip()
            lines[i]=""
        i += 1

    neigh=[]
    for k,str in enumerate(lines[l:]):
        if str != "":
            neigh.append(str)

    cdp_peers = 0
    for str in neigh:
        (device_id,local_int, local_int_no, hold_time, junk) = re.split("\s+", str, maxsplit=4)
        match = re.search("(\d)+$",local_int)
        if match:
            hold_time = local_int_no
            local_int_no=match.group(0)
        cdp_peers += 1
        # будет число соседних устройств всего. На одном порту может быть несколько устройств с CDP.
        # Из задания неясно, но может требоваться число интерфейсов с CDP-соседями
    return (cdp_run, cdp_peers)

def fetch_version(ssh_sess):
    # Задача 4: собрать данные о версии используемого ПО и тип (NPE/PE)
    output = ssh_sess.send_command("show version")
    return output

def parse_version(show_version):
    # Задача 4: собрать данные о версии используемого ПО и тип (NPE/PE)
    lines = show_version.splitlines();
    version=""
    device=""
    payload_encryption = "UNK"
    for str in lines:
        match = re.search("^Cisco IOS .*Software.*Version (.*)$", str)
        if match and version=="":
            version = match.group(1)

        match = re.search("^Cisco (.*) processor ", str, flags=re.IGNORECASE)
        if match:
            device = match.group(1)
        # PE/NPE определяю из cтроки "Cisco IOS Software, ISR Software (blah-blah)"
        # если там есть _NPE, то это NPE софт
        # иначе PE. А если это не ISR Software, то всеравно неясно чего должно получиться и остаётся UNK
        match = re.search(" ISR Software .([\w\-\_]+).", str)
        if match:
            payload_encryption = "PE "
            value = match.group(1)
            if (re.search("_NPE", value)):
                payload_encryption = "NPE"

    return (version,device,payload_encryption)

def fetch_ntp(ssh_sess):
    # Задача 5: проверка синхронизации часов
    output = ssh_sess.send_command("show ntp status")
    return output

def parse_ntp(show_ntp_status):
    # Задача 5: проверка синхронизации часов
    lines = show_ntp_status.splitlines();
    clock_status = ""
    for str in lines:
        match = re.search("^Clock is (\w+)", str)
        if match:
            clock_status = match.group(1)
            break

    if clock_status == "synchronized":
        return "Clock in Sync"
    else:
        return "Clock UNKNOWN"

def config_ntp(ssh_sess):
    # Задача 4: настроить на устройстве timezone..
    output = ssh_sess.send_command("ping %s repeat 4" % NTP_SERVER)

    lines = output.splitlines()
    pct_success = 0
    for str in lines:
        match = re.search("^Success rate is (\d+) percent", str)
        if match:
            pct_success = int(match.group(1))

    if pct_success < 49:
        print("!! NTP server %s not accessible (ping success: %d percent)" % (NTP_SERVER, pct_success), file=sys.stderr)
        return

    output = ssh_sess.send_config_set(CFG_COMMANDS)
    if re.search("% Invalid", output):
        print("!! NTP config most likely failed:\n%s" % output)
        # непонятно теперь чего с этим делать, бросаем как есть

    # сохранять конфиг не требуется в задаче

def iso8601(ts):
   return ts.strftime("%Y-%m-%dT%H-%M-%S")

def store_txt_file(filename, text):
    fp = open(filename, 'w')
    fp.write(text)
    fp.close

def main():
   ts = datetime.datetime.now()

   device_list = load_router_list(ROUTER_LIST)
   for device in device_list:
       print("- %s connecting .." % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       ssh_session = netmiko_connect(device)
       print("- %s connect ok   " % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)

       print("- %s show running " % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       (hostname, run_cfg) = fetch_running_conf(ssh_session)
       if run_cfg:
           store_txt_file("%s.%s.running-config.txt" % (hostname, iso8601(ts)), run_cfg)
       else:
           hostname="UNKNOWN"

       print("- %s show cdp     " % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       cdp_output = fetch_cdp(ssh_session)
       (cdp_enabled, num_cdp_peers) = parse_cdp(cdp_output)
       cdp_str = ""
       if cdp_enabled:
           cdp_str = "CDP is ON,%d peers" % num_cdp_peers
       else:
           cdp_str = "CDP is OFF"

       print("- %s show version" % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       version_output = fetch_version(ssh_session)
       (software,model,payload_encryption) = parse_version(version_output)

       print("- %s config ntp  " % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       cfg_output = config_ntp(ssh_session)

       print("- %s show ntp    " % device['mgmt_addr'], file=sys.stderr, end="\r", flush=True)
       ntp_output = fetch_ntp(ssh_session)
       clock_str = parse_ntp(ntp_output)

       print("- %s DONE        " % device['mgmt_addr'], file=sys.stderr, flush=True)

       # итоговый вывод для устройства
       print("%s|%s|%s|%s|%s|%s" % (hostname, model, software, payload_encryption, cdp_str, clock_str))

if __name__ == '__main__':
    main()
