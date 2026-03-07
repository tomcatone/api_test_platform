"""
API Test Platform v4 - GUI Launcher
Compile: pyinstaller --onefile --windowed --icon=icon.ico --name=API-TestPlatform-v4 launcher.py
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess, threading, sys, os, webbrowser, time, queue

# ── Single-instance lock (prevents multiple windows) ─────────────────────────
_MUTEX = None

def _acquire_single_instance():
    global _MUTEX
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, True, 'APITestPlatformV4_Singleton')
        err = ctypes.windll.kernel32.GetLastError()
        return err != 183
    except Exception:
        return True

# ── Path resolution ──────────────────────────────────────────────────────────
def _find_base_dir():
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    candidates.append(os.path.abspath(os.getcwd()))
    for c in candidates:
        if os.path.isfile(os.path.join(c, 'manage.py')):
            return c
    return candidates[0] if candidates else os.getcwd()

def _find_python():
    exe = os.path.normcase(os.path.abspath(sys.executable)) if sys.executable else ''
    if not getattr(sys, 'frozen', False):
        return sys.executable, 'sys.executable'
    import shutil
    for name in ('python', 'python3', 'py'):
        p = shutil.which(name)
        if p:
            p_norm = os.path.normcase(os.path.abspath(p))
            if p_norm != exe and 'python' in os.path.basename(p).lower():
                return p, f'PATH({name})'
    localapp = os.environ.get('LOCALAPPDATA', '')
    userprofile = os.environ.get('USERPROFILE', r'C:\Users\Administrator')
    for root in [
        os.path.join(userprofile, r'AppData\Local\Programs\Python\Python313'),
        os.path.join(userprofile, r'AppData\Local\Programs\Python\Python312'),
        os.path.join(userprofile, r'AppData\Local\Programs\Python\Python311'),
        os.path.join(localapp, r'Programs\Python\Python313'),
        os.path.join(localapp, r'Programs\Python\Python312'),
        r'C:\Python313', r'C:\Python312', r'C:\Python311', r'C:\Python310',
    ]:
        p = os.path.join(root, 'python.exe')
        if os.path.isfile(p):
            return p, f'fallback({root})'
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r'SOFTWARE\Python\PythonCore', r'SOFTWARE\WOW6432Node\Python\PythonCore'):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            ver = winreg.EnumKey(k, i)
                            try:
                                with winreg.OpenKey(hive, f'{sub}\\{ver}\\InstallPath') as ik:
                                    path = winreg.QueryValue(ik, '')
                                    p = os.path.join(path.strip(), 'python.exe')
                                    if os.path.isfile(p):
                                        return p, f'registry({ver})'
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        pass
    return None, 'not found'


BASE_DIR    = _find_base_dir()
VENV_DIR    = os.path.join(BASE_DIR, 'venv')
VENV_PYTHON = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
VENV_PIP    = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
MANAGE_PY   = os.path.join(BASE_DIR, 'manage.py')
REQ_TXT     = os.path.join(BASE_DIR, 'requirements.txt')
PORT        = 8000
server_proc = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('API 接口测试平台 v4')
        self.geometry('560x440')
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self._q = queue.Queue()
        self._build_ui()
        self._poll()
        self.after(300, lambda: threading.Thread(target=self._flow, daemon=True).start())

    def _build_ui(self):
        hdr = tk.Frame(self, bg='#1e3a5f', height=56)
        hdr.pack(fill='x')
        tk.Label(hdr, text='API 接口测试平台 v4',
                 font=('Microsoft YaHei', 14, 'bold'),
                 bg='#1e3a5f', fg='white').pack(pady=14)
        self.status_var = tk.StringVar(value='正在初始化...')
        bar = tk.Frame(self, bg='#f0f4f8')
        bar.pack(fill='x')
        tk.Label(bar, textvariable=self.status_var, font=('Microsoft YaHei', 9),
                 bg='#f0f4f8', fg='#374151', anchor='w').pack(side='left', padx=12, pady=6)
        self.progress = ttk.Progressbar(self, mode='indeterminate', length=560)
        self.progress.pack(fill='x')
        self.logbox = scrolledtext.ScrolledText(
            self, font=('Consolas', 8), height=16,
            bg='#1e1e1e', fg='#d4d4d4', insertbackground='white', state='disabled')
        self.logbox.pack(fill='both', expand=True, padx=8, pady=(6, 0))
        self.logbox.tag_config('b', foreground='#60a5fa')
        self.logbox.tag_config('g', foreground='#34d399')
        self.logbox.tag_config('r', foreground='#f87171')
        self.logbox.tag_config('y', foreground='#f59e0b')
        self.logbox.tag_config('s', foreground='#94a3b8')
        bf = tk.Frame(self, pady=8); bf.pack(fill='x', padx=8)
        self.btn_open = tk.Button(bf, text='打开浏览器', state='disabled',
                                  bg='#2563eb', fg='white', font=('Microsoft YaHei', 9),
                                  relief='flat', padx=12,
                                  command=lambda: webbrowser.open(f'http://127.0.0.1:{PORT}'))
        self.btn_open.pack(side='left', padx=(0, 8))
        self.btn_stop = tk.Button(bf, text='停止服务', state='disabled',
                                  bg='#dc2626', fg='white', font=('Microsoft YaHei', 9),
                                  relief='flat', padx=12, command=self.stop_server)
        self.btn_stop.pack(side='left')
        self.url_lbl = tk.Label(bf, text='', font=('Microsoft YaHei', 9), fg='#6b7280')
        self.url_lbl.pack(side='right', padx=4)

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]
                if kind == 'log':
                    _, text, tag = msg
                    self.logbox.configure(state='normal')
                    self.logbox.insert('end', text + '\n', (tag,) if tag else ())
                    self.logbox.configure(state='disabled')
                    self.logbox.see('end')
                elif kind == 'status':
                    self.status_var.set(msg[1])
                elif kind == 'pstart':
                    self.progress.start(12)
                elif kind == 'pstop':
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=100)
                elif kind == 'ready':
                    self.btn_open.config(state='normal')
                    self.btn_stop.config(state='normal')
                    self.url_lbl.config(text=f'http://127.0.0.1:{PORT}')
                elif kind == 'srvstop':
                    self.btn_stop.config(state='disabled')
                elif kind == 'port_changed':
                    new_port = msg[1]
                    self.btn_open.config(command=lambda p=new_port: webbrowser.open(f'http://127.0.0.1:{p}'))
                    self.url_lbl.config(text=f'http://127.0.0.1:{new_port}')
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _log(self, text, tag=None):
        self._q.put(('log', text, tag))

    def _status(self, text):
        self._q.put(('status', text))

    def _run(self, cmd, label):
        self._log(f'> {label}', 'b')
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=BASE_DIR, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log('  ' + line)
            proc.wait()
            return proc.returncode
        except FileNotFoundError as e:
            self._log(f'  [未找到] {e}', 'r')
            return 1
        except Exception as e:
            self._log(f'  [错误] {e}', 'r')
            return 1

    def _flow(self):
        self._q.put(('pstart',))
        self._log(f'项目目录 : {BASE_DIR}', 's')
        self._log(f'venv     : {VENV_DIR}', 's')
        self._log(f'manage.py: {"OK" if os.path.isfile(MANAGE_PY) else "NOT FOUND!"}', 's')

        sys_python, src = _find_python()
        self._log(f'Python   : {sys_python}  [{src}]', 's')

        if not sys_python:
            self._status('错误：未找到 Python')
            self._log('请安装 Python 3.10+ 并勾选 "Add Python to PATH"', 'r')
            self._log('下载: https://www.python.org/downloads/', 'r')
            self._q.put(('pstop',))
            return

        if not os.path.isfile(VENV_PYTHON):
            self._status('[1/3] 创建虚拟环境...')
            ret = self._run([sys_python, '-m', 'venv', VENV_DIR], '创建虚拟环境')
            if ret != 0 or not os.path.isfile(VENV_PYTHON):
                self._status('错误：虚拟环境创建失败')
                self._log('请确认 Python 含 venv 模块（默认包含）', 'r')
                self._q.put(('pstop',))
                return

            self._status('[2/3] 安装依赖（首次约需 2-5 分钟，请耐心等待）...')
            ret = self._run([VENV_PIP, 'install', '-r', REQ_TXT, '-q'], '安装依赖')
            if ret != 0:
                self._status('切换清华镜像重试...')
                ret = self._run([VENV_PIP, 'install', '-r', REQ_TXT,
                                 '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple', '-q'],
                                '安装依赖（清华镜像）')
            if ret != 0:
                self._status('错误：依赖安装失败')
                self._q.put(('pstop',))
                return

            self._status('[3/3] 初始化数据库...')
            ret = self._run([VENV_PYTHON, MANAGE_PY, 'migrate', '--verbosity', '0'], '初始化数据库')
            if ret != 0:
                self._status('错误：数据库初始化失败')
                self._q.put(('pstop',))
                return
        else:
            self._status('检查/补装依赖...')
            ret = self._run([VENV_PIP, 'install', '-r', REQ_TXT, '-q'], '检查/补装依赖')
            if ret != 0:
                self._run([VENV_PIP, 'install', '-r', REQ_TXT,
                           '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple', '-q'],
                          '补装依赖（镜像）')
            self._status('检查数据库...')
            ret2 = self._run([VENV_PYTHON, MANAGE_PY, 'migrate', '--verbosity', '0'], '数据库迁移')
            if ret2 != 0:
                self._log('  [警告] 数据库迁移返回错误，将尝试继续启动', 'y')

        self._status('启动服务中...')
        self._log(f'> 启动 Django (端口 {PORT})', 'g')
        self._start_server()

    def _start_server(self):
        global server_proc, PORT
        # Auto-detect available port
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(('127.0.0.1', PORT)) == 0:
                    PORT = 8080
                    self._log(f'  端口 8000 已占用，自动切换至 {PORT}', 'y')
                    self._q.put(('port_changed', PORT))
        except Exception:
            pass
        try:
            server_proc = subprocess.Popen(
                [VENV_PYTHON, MANAGE_PY, 'runserver', f'0.0.0.0:{PORT}'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=BASE_DIR, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            self._log(f'启动失败: {e}', 'r')
            self._status('错误：服务启动失败')
            self._q.put(('pstop',))
            return

        self._q.put(('pstop',))
        self._q.put(('ready',))
        self._status(f'运行中 ● http://127.0.0.1:{PORT}')
        self._log(f'服务已启动 → http://127.0.0.1:{PORT}', 'g')

        time.sleep(1.5)
        webbrowser.open(f'http://127.0.0.1:{PORT}')

        for line in server_proc.stdout:
            line = line.rstrip()
            if line:
                self._log(line, 'r' if 'error' in line.lower() else 's')

        self._status('服务已停止')
        self._q.put(('srvstop',))
        self._log('服务进程已退出', 'y')

    def stop_server(self):
        global server_proc
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            self._log('已发送停止信号', 'y')
            self._q.put(('srvstop',))

    def on_close(self):
        self.stop_server()
        time.sleep(0.3)
        self.destroy()


if __name__ == '__main__':
    if not _acquire_single_instance():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                'API 接口测试平台已经在运行中！\n请查看任务栏。',
                'API Test Platform', 0x40)
        except Exception:
            pass
        sys.exit(0)

    app = App()
    app.mainloop()
