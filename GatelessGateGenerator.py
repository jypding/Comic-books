bl_info = {
    "name": "GatelessGateGenerator",
    "author": "Trae",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "description": "天门语音书生成器主入口，整合导出与构建功能",
    "category": "Addon",
}

import bpy
import sys
import os
import importlib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

# --- Bridge Server Configuration ---
BLENDER_BRIDGE_PORT = 9876
BLENDER_BRIDGE_HOST = "127.0.0.1"

# Global variable to hold the HTTP server instance
httpd = None
server_thread = None

class BlenderCodeExecutionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/execute_code':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                request_payload = json.loads(post_data.decode('utf-8'))
                code_to_execute = request_payload.get('code')
                if code_to_execute:
                    print(f"[BlenderBridge] Executing code: {code_to_execute[:100]}...")
                    # Execute the code within Blender's context
                    exec(code_to_execute, globals())
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "Code executed"}).encode('utf-8'))
                else:
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "No code provided"}).encode('utf-8'))
            except Exception as e:
                print(f"[BlenderBridge] Error executing code: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'404 Not Found')

    def log_message(self, format, *args):
        # Suppress HTTP server logging to Blender console
        pass


# 确保当前目录在 sys.path 中
addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

# 导入核心模块
try:
    import blender_export_reading
    importlib.reload(blender_export_reading)
except ImportError as e:
    print(f"GatelessGateGenerator: 无法加载 blender_export_reading.py - {e}")

def register():
    global httpd, server_thread
    print("GatelessGateGenerator: 正在注册插件...")
    if "blender_export_reading" in sys.modules:
        blender_export_reading.register()
        print("GatelessGateGenerator: blender_export_reading 注册完成")

        # Start the HTTP server in a new thread
        try:
            httpd = HTTPServer((BLENDER_BRIDGE_HOST, BLENDER_BRIDGE_PORT), BlenderCodeExecutionHandler)
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()
            print(f"[BlenderBridge] Server started on http://{BLENDER_BRIDGE_HOST}:{BLENDER_BRIDGE_PORT}")
        except Exception as e:
            print(f"[BlenderBridge] Failed to start server: {e}")

    else:
        print("GatelessGateGenerator: 注册失败，模块未加载")

def unregister():
    global httpd, server_thread
    print("GatelessGateGenerator: 正在注销插件...")
    if "blender_export_reading" in sys.modules:
        blender_export_reading.unregister()

    # Shut down the HTTP server
    if httpd:
        httpd.shutdown()
        server_thread.join()
        print("[BlenderBridge] Server stopped.")

if __name__ == "__main__":
    register()
