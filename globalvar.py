import os
import threading

lock=threading.Lock()
g_config = {}
#peer_addr="127.0.0.1"
peer_addr="192.168.1.7"
is_peer_alive=False
g_share_path = os.path.join(os.getcwd(),'share')
g_previous_files={}
g_host_name=""