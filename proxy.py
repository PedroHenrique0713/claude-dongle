import os, json, subprocess, time, signal

PROXY_PORT = 8081
STATE_FILE = "/tmp/claude-monitor-proxy.json"
ADDON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_addon.py")
CA_CERT = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")

_proc = None

def _mitmdump_path():
    import shutil
    return shutil.which("mitmdump") or os.path.expanduser("~/.pyenv/shims/mitmdump")

def start():
    global _proc
    if is_running():
        return True
    cmd = [
        _mitmdump_path(), "-p", str(PROXY_PORT),
        "-s", ADDON_PATH,
        "--set", "block_global=false",
    ]
    try:
        _proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        time.sleep(1.5)
        return is_running()
    except FileNotFoundError as e:
        print(f"[proxy] mitmdump not found: {e}")
        return False

def stop():
    global _proc
    if _proc:
        try:
            os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
        except (ProcessLookupError, AttributeError):
            pass
        try:
            _proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(_proc.pid), signal.SIGKILL)
            except:
                pass
        _proc = None
    pkill_mitm()

def pkill_mitm():
    try:
        subprocess.run(["pkill", "-9", "-f", "mitmdump"], capture_output=True, timeout=3)
    except:
        pass

def is_running():
    if _proc and _proc.poll() is None:
        return True
    r = subprocess.run(
        ["pgrep", "-f", "mitmdump.*8081"],
        capture_output=True, timeout=3
    )
    return r.returncode == 0

def get_latest():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        age = time.time() - data.get("_updated_at", 0)
        if age > 3600:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None

def wrapper_env():
    if not os.path.exists(CA_CERT):
        return {}
    return {
        "NODE_EXTRA_CA_CERTS": CA_CERT,
        "HTTPS_PROXY": f"http://localhost:{PROXY_PORT}",
        "HTTP_PROXY": f"http://localhost:{PROXY_PORT}",
    }

def wrapper_script_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude-wrapper.sh")
