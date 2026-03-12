# ssh_client.py
import paramiko
import sys

def run_ssh_command(host, username, password, command, port=22, timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=username, password=password, timeout=timeout)
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode()
    err = stderr.read().decode()
    client.close()
    return out, err

if __name__ == "__main__":
    host = sys.argv[1]
    user = sys.argv[2]
    pwd = sys.argv[3]
    cmd = " ".join(sys.argv[4:])
    out, err = run_ssh_command(host, user, pwd, cmd)
    print("OUTPUT:\n", out)
    if err:
        print("ERROR:\n", err)
