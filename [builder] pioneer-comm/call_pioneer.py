#!/usr/bin/env python3
"""Pioneer 管道通信：本地 → SSH → TencentCloud → hermes chat -q"""
import subprocess, shlex, sys, json

CLOUD_SSH_HOST = "43.139.75.69"

def call_pioneer(msg: str, timeout: int = 120) -> dict:
    """调用云端 Pioneer，返回 {reply, session_id}"""
    remote_cmd = shlex.join(["hermes", "chat", "-q", msg, "-Q"])
    cmd = ["ssh", CLOUD_SSH_HOST, remote_cmd]
    
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, stdin=subprocess.DEVNULL, **flags)
    
    output = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        output.append(line)
    
    proc.wait(timeout=timeout)
    proc.stdout.close()
    full = "".join(output)
    
    # 提取 session_id
    session_id = ""
    for line in output:
        if line.startswith("session_id:"):
            session_id = line.strip().split(":", 1)[1].strip()
    
    # 去掉 warning 行和 session_id 行，只留回复
    reply_lines = [l for l in output 
                   if not l.startswith("Warning:") 
                   and not l.startswith("session_id:")]
    reply = "".join(reply_lines).strip()
    
    return {"reply": reply, "session_id": session_id, "raw": full}

if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "hi"
    result = call_pioneer(msg)
    print(f"\n=== Pioneer ({result['session_id']}) ===")
    print(result["reply"])
