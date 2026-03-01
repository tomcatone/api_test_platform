"""
API Test Platform v4 - GUI Launcher
Compile with: pyinstaller --onefile --windowed --icon=icon.ico --name=启动平台 launcher.py
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess, threading, sys, os, webbrowser, time, signal

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
VENV_PYTHON = os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe')
VENV_PIP    = os.path.join(BASE_DIR, 'venv', 'Scripts', 'pip.exe')
MANAGE_PY   = os.path.join(BASE_DIR, 'manage.py')
REQ_TXT     = os.path.join(BASE_DIR, 'requirements.txt')
PORT        = 8000

server_proc = None

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('API 接口测试平台 v4')
        self.geometry('520x400')
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self._build_ui()
        self.after(300, self.start_flow)

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg='#1e3a5f', height=56)
        hdr.pack(fill='x')
        tk.Label(hdr, text='API 接口测试平台 v4', font=('Microsoft YaHei', 14, 'bold'),
                 bg='#1e3a5f', fg='white').pack(pady=14)

        # Status bar
        self.status_var = tk.StringVar(value='正在初始化...')
        status_bar = tk.Frame(self, bg='#f0f4f8')
        status_bar.pack(fill='x', padx=0)
        tk.Label(status_bar, textvariable=self.status_var, font=('Microsoft YaHei', 9),
                 bg='#f0f4f8', fg='#374151', anchor='w').pack(side='left', padx=12, pady=6)

        # Progress bar
        self.progress = ttk.Progressbar(self, mode='indeterminate', length=520)
        self.progress.pack(fill='x')

        # Log area
        self.log = scrolledtext.ScrolledText(self, font=('Consolas', 8), height=14,
                                              bg='#1e1e1e', fg='#d4d4d4',
                                              insertbackground='white', state='disabled')
        self.log.pack(fill='both', expand=True, padx=8, pady=(6,0))

        # Buttons
        btn_frame = tk.Frame(self, pady=8)
        btn_frame.pack(fill='x', padx=8)
        self.btn_open = tk.Button(btn_frame, text='打开浏览器', state='disabled',
                                   bg='#2563eb', fg='white', font=('Microsoft YaHei', 9),
                                   relief='flat', padx=12,
                                   command=lambda: webbrowser.open(f'http://127.0.0.1:{PORT}'))
        self.btn_open.pack(side='left', padx=(0,8))
        self.btn_stop = tk.Button(btn_frame, text='停止服务', state='disabled',
                                   bg='#dc2626', fg='white', font=('Microsoft YaHei', 9),
                                   relief='flat', padx=12, command=self.stop_server)
        self.btn_stop.pack(side='left')
        self.url_label = tk.Label(btn_frame, text='', font=('Microsoft YaHei', 9),
                                   fg='#6b7280')
        self.url_label.pack(side='right', padx=4)

    def log_write(self, text, color=None):
        self.log.configure(state='normal')
        start = self.log.index('end')
        self.log.insert('end', text + '\n')
        if color:
            end = self.log.index('end')
            tag = f'c_{color}'
            self.log.tag_config(tag, foreground=color)
            self.log.tag_add(tag, start, end)
        self.log.configure(state='disabled')
        self.log.see('end')

    def set_status(self, text):
        self.status_var.set(text)
        self.update_idletasks()

    def run_cmd(self, cmd, label):
        self.log_write(f'> {label}', '#60a5fa')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 cwd=BASE_DIR, text=True, encoding='utf-8', errors='replace',
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.log_write('  ' + line)
        proc.wait()
        return proc.returncode

    def start_flow(self):
        threading.Thread(target=self._flow, daemon=True).start()

    def _flow(self):
        self.progress.start(12)

        # Step 1: check venv
        if not os.path.exists(VENV_PYTHON):
            self.set_status('[1/3] 创建虚拟环境...')
            ret = self.run_cmd([sys.executable, '-m', 'venv', 'venv'], '创建虚拟环境')
            if ret != 0:
                self.set_status('错误：虚拟环境创建失败')
                self.log_write('创建失败，请检查 Python 安装', '#f87171')
                self.progress.stop()
                return

            self.set_status('[2/3] 安装依赖（请稍候）...')
            ret = self.run_cmd([VENV_PIP, 'install', '-r', REQ_TXT, '-q'], '安装依赖')
            if ret != 0:
                self.set_status('切换镜像重试...')
                ret = self.run_cmd([VENV_PIP, 'install', '-r', REQ_TXT,
                                    '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple', '-q'],
                                   '安装依赖（镜像）')
            if ret != 0:
                self.set_status('错误：依赖安装失败')
                self.log_write('请检查网络连接', '#f87171')
                self.progress.stop()
                return

            self.set_status('[3/3] 初始化数据库...')
            self.run_cmd([VENV_PYTHON, MANAGE_PY, 'makemigrations', '--verbosity', '0'], '数据库迁移')
            ret = self.run_cmd([VENV_PYTHON, MANAGE_PY, 'migrate', '--verbosity', '0'], '数据库初始化')
            if ret != 0:
                self.set_status('错误：数据库初始化失败')
                self.progress.stop()
                return
        else:
            self.set_status('检查数据库更新...')
            self.run_cmd([VENV_PYTHON, MANAGE_PY, 'migrate', '--verbosity', '0'], '数据库迁移')

        # Step 2: Start server
        self.set_status('启动服务中...')
        self.log_write(f'> 启动 Django 服务 (端口 {PORT})', '#34d399')
        self._start_server()

    def _start_server(self):
        global server_proc
        server_proc = subprocess.Popen(
            [VENV_PYTHON, MANAGE_PY, 'runserver', f'0.0.0.0:{PORT}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=BASE_DIR, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.progress.stop()
        self.progress.configure(mode='determinate', value=100)

        self.set_status(f'运行中 ● http://127.0.0.1:{PORT}')
        self.url_label.config(text=f'http://127.0.0.1:{PORT}')
        self.btn_open.config(state='normal')
        self.btn_stop.config(state='normal')
        self.log_write(f'服务已启动 → http://127.0.0.1:{PORT}', '#34d399')

        # Auto open browser
        time.sleep(1.5)
        webbrowser.open(f'http://127.0.0.1:{PORT}')

        # Read server output
        for line in server_proc.stdout:
            line = line.rstrip()
            if line:
                color = '#f87171' if 'error' in line.lower() else '#94a3b8'
                self.log_write(line, color)

        self.set_status('服务已停止')
        self.btn_stop.config(state='disabled')
        self.log_write('服务进程已退出', '#f59e0b')

    def stop_server(self):
        global server_proc
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            self.log_write('已发送停止信号...', '#f59e0b')
            self.btn_stop.config(state='disabled')

    def on_close(self):
        self.stop_server()
        time.sleep(0.5)
        self.destroy()

if __name__ == '__main__':
    app = App()
    app.mainloop()
