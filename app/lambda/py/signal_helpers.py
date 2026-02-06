import os
import signal


def _forward_signal_to_proc(proc, sig):
    try:
        pid = getattr(proc, 'pid', None)
        if not pid:
            return
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, sig)
        except Exception:
            os.kill(pid, sig)
    except Exception:
        pass


def _shutdown_children(get_procs, signum, frame):
    try:
        procs_info = get_procs() or {}
        for name in ('_setup_auth_proc', '_setup_proc'):
            proc = procs_info.get(name)
            try:
                if proc and getattr(proc, 'poll', lambda: 1)() is None:
                    # Forward signal
                    try:
                        _forward_signal_to_proc(proc, signum)
                    except Exception:
                        pass
                    # wait briefly for graceful exit
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        try:
                            proc.kill()
                        except Exception:
                            pass
            except Exception:
                # ignore errors per best-effort shutdown
                pass

        # Close pty master fd if provided
        master_fd = procs_info.get('master_fd')
        try:
            if master_fd:
                try:
                    os.close(master_fd)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def register_signal_handlers(get_procs_callable):
    try:
        signal.signal(signal.SIGINT, lambda s, f: _shutdown_children(get_procs_callable, s, f))
        signal.signal(signal.SIGTERM, lambda s, f: _shutdown_children(get_procs_callable, s, f))
    except Exception:
        # Best-effort: some environments may not allow signal registration
        pass
