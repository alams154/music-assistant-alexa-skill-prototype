import os
import re
import time

def sanitize_log(s: str) -> str:
    try:
        if not isinstance(s, str):
            s = str(s)
    except Exception:
        s = ''
    s = s.replace('\\u001b', '')
    s = s.replace('\r', '')
    try:
        s = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', s)
    except Exception:
        pass
    if 'authorization code' in s.lower():
        s = re.sub(r'(?i)(authorization code[:]?\s*).*', r"\1<REDACTED-AUTH-CODE>", s)
    return s


def enqueue_setup_log(logs, line: str):
    try:
        logs.append(sanitize_log(line))
    except Exception:
        try:
            logs.append(str(line))
        except Exception:
            pass


def setup_reader_thread(proc, enqueue_func, prefix=None):
    try:
        for line in proc.stdout:
            if not line:
                continue
            text = line.rstrip('\n')
            if prefix:
                text = f'[{prefix}] {text}'
            enqueue_func(text)
    except Exception as e:
        enqueue_func(f"[reader error] {e}")


def read_master_loop(master_fd, enqueue_func, prefix=None):
    try:
        buf = b''
        while True:
            try:
                chunk = os.read(master_fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                text = line.decode('utf-8', errors='replace')
                if prefix:
                    text = f'[{prefix}] {text}'
                enqueue_func(text)
            try:
                s = chunk.decode('utf-8', errors='replace')
                for m in re.findall(r"https?://[^\s'\"]+", s):
                    txt = m
                    if prefix:
                        txt = f'[{prefix}] {txt}'
                    enqueue_func(txt)
            except Exception:
                pass
        if buf:
            text = buf.decode('utf-8', errors='replace')
            if text.strip():
                if prefix:
                    text = f'[{prefix}] {text}'
                enqueue_func(text)
    except Exception as e:
        enqueue_func(f"[pty reader error] {e}")
