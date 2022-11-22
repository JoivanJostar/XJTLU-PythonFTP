import argparse,socket,os,json, globalvar
import shutil
import struct
import sys
import threading
import signal
import time
#this is used to init the config first, it is unused in the final version code
def log(msg):
    if globalvar.g_config["log_info"] == 1:
        print(f"IP[{globalvar.g_host_name}] PID[{os.getpid()}]: "+str(msg))
    else:
        return 0

def init_config():
    try:
        cfg_file = open("./config.json", "w")
        config = {
            "buffer_size": 5242880,
            # 5M
            "tcp_port": 20220,
            "udp_port": 44552,
            "log_info":1
        }
        json.dump(config, cfg_file)
    except Exception as e:
        log(f"init config failuer with error {e}")
def init_previous():
    try:
        previous_file = open("./previous.json", "w")
        previos = {
        }
        json.dump(previos, previous_file)
    except Exception as e:
        log(f"init previous.json failuer with error {e}")

def load_config():
    try:
        cfg_file=open("./config.json","r")
        globalvar.g_config=json.load(cfg_file)
    except Exception as e:
        #log(f"load config json file failuer")
        return False
    return True
def load_previous():
    try:
        previous_file=open("./previous.json","r")
        tmp=json.load(previous_file)
        for key in tmp.keys():
            globalvar.g_previous_files[key]=tuple((tmp[key][0],tmp[key][1]))
    except Exception as e:
        log(f"load previous json file failuer {e}")
        return False
    return True

def save_previous():
    try:
        previous_file = open("./previous.json", "w")
        previous_file.close()
    except Exception as e:
        init_previous()

    previous_file = open("./previous.json", "w")
    json.dump(globalvar.g_previous_files,previous_file)
    previous_file.close()

def _argparse():
    parser = argparse.ArgumentParser(description="")
    parser.add_argument('--ip')
    return parser.parse_args()

def heart_beat():
    udp_sockfd = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    #set the port to reused that if the program restart it can quickly listen the port success
    udp_sockfd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sockfd.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_sockfd.setblocking(False)
    udp_sockfd.bind( ("0.0.0.0",globalvar.g_config["udp_port"]) )
    data = ("",)
    while True:
        try:
            udp_sockfd.sendto("SYN".encode(), (globalvar.peer_addr, globalvar.g_config["udp_port"]))
        except Exception as e:
            "pass"
        try:
            data = udp_sockfd.recvfrom(10)
        except Exception as e :
            continue
        if data[0].decode()=="SYN":
            globalvar.lock.acquire()
            globalvar.is_peer_alive=True
            globalvar.lock.release()
        time.sleep(0.1)


def send_to_peer(path,size):
    # the max length of a file full path is 260 byte on windows ,4096 on linux
    # the file size may be so long that we need 8 bytes
    pack_head=struct.pack("!4096sQ",path.encode(),size)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((globalvar.peer_addr, globalvar.g_config["tcp_port"]))
    except :
        # peer exited refuse to connect
        return 0
    try:
        sock.send(pack_head)
    except:
        return 0
    log(f"send the file {path} size={size}'s head sucess")
    try:
        data=sock.recv(100)
        if len(data)==0:
            return 0
        else:
            t_need=struct.unpack("!Q",data)
            beg_pos = t_need[0]
    except:
        return 0
    file = open(path, "rb")
    file.seek(beg_pos)
    while True:
        data = file.read(globalvar.g_config["buffer_size"])
        if not data:
            break
        try:
            sock.send(data)
        except:
            log("send failure when send piece")
            file.close()
            sock.close()
            return 0
    file.close()
    sock.close()
    return 1


def set_sort_func(set_item):
    return [len(set_item[0]),set_item[0]]
def monitor_thread_proc():

    #the difference between the current file dict and the old file dict
    changed_files = set()
    #the current file dict
    cur_files = dict()
    log("begins to check the file change")
    while True:
        cur_files = {}
        for dir_path,dirs,files in os.walk(globalvar.g_share_path):
            for file in files:
                #  localpath/share/A/a    to      ./share/A/a
                path = os.path.join(dir_path, file).replace(os.getcwd(), '.')
                size=os.path.getsize(path)
                ftime=os.path.getmtime(path)
                cur_files[path]=(size,ftime)

        changed_files = set(cur_files.items()).difference(set(globalvar.g_previous_files.items()))
        set2list_sort=list(changed_files)
        set2list_sort=sorted(set2list_sort,key=set_sort_func)
        #changed_files=set(set2list_sort)
        if 0!=len(set2list_sort) :
            log(f"Find {len(set2list_sort)} changes")
            log(set2list_sort)
            for item in set2list_sort:
                #("path",(szie,time))
                ret=send_to_peer(item[0],item[1][0])
                # has been sendto peer
                if ret==1:
                    globalvar.lock.acquire()
                    globalvar.g_previous_files[item[0]] = tuple(item[1])
                    save_previous()
                    globalvar.lock.release()
                else:
                    log("send fail")
                    break
                #sender.call_sender(peer_ip_address, item)
        time.sleep(0.2)



def recv_thread_func():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', globalvar.g_config["tcp_port"]))
    sock.listen(10)
    log("bind tcp socket port success")
    while True:
        connection,addr=sock.accept()
        #if not alive close sock
        packsize=struct.calcsize('!4096sQ')
        recv_data=connection.recv(packsize)
        if len(recv_data)!=packsize:
            #peer may be offline
            connection.close()
            continue
        path,size=struct.unpack('!4096sQ', recv_data)
        path = path.decode().strip('\00')
        log(f"recv the file {path} 's {len(recv_data)} size pack head")
        (dirname, filename) = os.path.split(path)
        if not os.path.exists("./temp"):
            os.makedirs("./temp")
        temp_file="./temp/"+filename

        if not os.path.exists(dirname):
            os.makedirs(dirname)

        received=0
        if os.path.exists(temp_file):
            received=os.path.getsize(temp_file)
            log(f"[CRITICAL] find a break point file size= {received}")

        connection.send(struct.pack("!Q",received))
        openfile=open(temp_file,"ab")
        while True:
            if received==size:
                break
            try:
                data=connection.recv(globalvar.g_config["buffer_size"])
            except:
                break
            if len(data)==0:
                break
            received+=len(data)
            openfile.write(data)

        openfile.close()
        connection.close()
        if received==size:
            if os.path.exists(path):
                os.remove(path)
            shutil.move(temp_file, dirname)
            ftime = os.path.getmtime(path)
            #加锁
            globalvar.lock.acquire()
            globalvar.g_previous_files[path]=(size,ftime)
            save_previous()
            globalvar.lock.release()
            log(f"recv the file {path} complete !")



if __name__ == "__main__":
    #load the config
    if not load_config():
        init_config()
        load_config()
    if not load_previous():
        init_previous()
        load_previous()
    #print(globalvar.g_config)
    #print(f"previous files\n{globalvar.g_previous_files}")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    globalvar.g_host_name=""
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        globalvar.g_host_name=ip
    except:
        globalvar.g_host_name = ""
    arg=_argparse()
    globalvar.peer_addr=arg.ip

    log(f"the peer ip address is {globalvar.peer_addr}")

    heart_thread=threading.Thread(target=heart_beat)
    recv_thread=threading.Thread(target=recv_thread_func)
    monitor_thread=threading.Thread(target=monitor_thread_proc)
    heart_thread.start()
    while True:
        globalvar.lock.acquire()
        is_alive=globalvar.is_peer_alive;
        globalvar.lock.release()
        if is_alive==True :
            break

    recv_thread.start()
    monitor_thread.start()
    recv_thread.join()
    monitor_thread.join()
    heart_thread.join()


