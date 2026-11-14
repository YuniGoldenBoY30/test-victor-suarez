"""Despliegue en el VPS con paramiko (solo acceso por clave). Ver docs/DESPLIEGUE.md.

    python deploy/desplegar.py preflight            # solo lectura
    python deploy/desplegar.py app [--ref HEAD]     # sube la versión y docker compose up
    python deploy/desplegar.py vhost [--reemplazar] # instala el vhost de Apache
    python deploy/desplegar.py humo                 # pruebas de humo desde el VPS

Opción global --dry-run: muestra lo que haría sin conectarse.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from comun import RAIZ, conectar_con_clave, destino, ejecutar, env_para_servidor, leer_env, sudo

DOMINIO = "test.zenixtech.ai"
DIR_REMOTO = "/opt/project-ai-role"
VHOST_LOCAL = RAIZ / "deploy" / "apache" / f"{DOMINIO}.conf"
VHOST_REMOTO = f"/etc/apache2/sites-available/{DOMINIO}.conf"
PUERTO_LOCAL = 8080
MODULOS = ("proxy", "proxy_http", "headers", "ssl", "rewrite")


def preflight(cli, s: str) -> None:
    ejecutar(cli, "uname -a; . /etc/os-release && echo $PRETTY_NAME; whoami", comprobar=False)
    ejecutar(cli, "apache2 -v 2>&1 | head -1", comprobar=False)
    ejecutar(cli, f"{s}apache2ctl -M 2>/dev/null | grep -E '(proxy|proxy_http|headers|ssl|rewrite)_module' || true", comprobar=False)
    ejecutar(cli, "ls /etc/apache2/sites-enabled/", comprobar=False)
    ejecutar(cli, f"grep -ril 'ServerName[[:space:]]*{DOMINIO}' /etc/apache2/sites-enabled/ || echo 'ningún vhost con {DOMINIO}'", comprobar=False)
    ejecutar(cli, f"grep -rih 'ProxyPass\\|DocumentRoot' $(grep -ril 'ServerName[[:space:]]*{DOMINIO}' /etc/apache2/sites-enabled/ 2>/dev/null) 2>/dev/null | sort -u || true", comprobar=False)
    ejecutar(cli, "docker --version; docker compose version", comprobar=False)
    ejecutar(cli, f"ss -ltnp 2>/dev/null | grep -E ':(80|443|{PUERTO_LOCAL})\\b' || true", comprobar=False)
    ejecutar(cli, f"df -h / | tail -1; ls -la {DIR_REMOTO} 2>/dev/null || echo '{DIR_REMOTO} no existe'", comprobar=False)


def empaquetar(ref: str) -> tuple[Path, str]:
    sha = subprocess.check_output(["git", "rev-parse", "--short", ref], cwd=RAIZ, text=True).strip()
    if subprocess.run(["git", "cat-file", "-e", f"{ref}:docker-compose.yml"], cwd=RAIZ, capture_output=True).returncode != 0:
        sys.exit(f"{ref} no contiene docker-compose.yml: aún no hay nada que desplegar (paso s10).")
    tar = Path(tempfile.gettempdir()) / f"project-ai-role-{sha}.tar.gz"
    subprocess.check_call(["git", "archive", "--format=tar.gz", "-o", str(tar), ref], cwd=RAIZ)
    return tar, sha


def app(cli, s: str, ref: str, datos: dict[str, str]) -> None:
    tar, sha = empaquetar(ref)
    rel = f"{DIR_REMOTO}/releases/{sha}"
    ejecutar(cli, f"{s}mkdir -p {rel} {DIR_REMOTO}/shared")
    sftp = cli.open_sftp()
    remoto_tar = f"/tmp/{tar.name}"
    print(f"sftp {tar.name} -> {remoto_tar}")
    sftp.put(str(tar), remoto_tar)
    print(f"sftp .env (sin VPS_*) -> {DIR_REMOTO}/shared/.env")
    with sftp.open("/tmp/project-ai-role.env", "w") as f:
        f.chmod(0o600)  # antes de escribir la clave de NVIDIA
        f.write(env_para_servidor(datos).encode("utf-8"))
    sftp.close()
    ejecutar(cli, f"{s}install -m 600 /tmp/project-ai-role.env {DIR_REMOTO}/shared/.env && rm -f /tmp/project-ai-role.env")
    ejecutar(cli, f"{s}tar -xzf {remoto_tar} -C {rel} && rm -f {remoto_tar} && {s}ln -sfn {DIR_REMOTO}/shared/.env {rel}/.env")
    ejecutar(cli, f"{s}ln -sfn {rel} {DIR_REMOTO}/current")
    ejecutar(cli, f"cd {DIR_REMOTO}/current && {s}docker compose -p project-ai-role up -d --build --remove-orphans", timeout=1800)
    ejecutar(cli, f"cd {DIR_REMOTO}/current && {s}docker compose -p project-ai-role ps")
    ejecutar(cli, f"for i in $(seq 1 30); do curl -fsS http://127.0.0.1:{PUERTO_LOCAL}/api/health && exit 0; sleep 2; done; exit 1")


def vhost(cli, s: str, reemplazar: bool) -> None:
    _, otros = ejecutar(
        cli,
        f"grep -ril 'ServerName[[:space:]]*{DOMINIO}' /etc/apache2/sites-enabled/ | grep -v '{DOMINIO}.conf$' || true",
        comprobar=False,
    )
    otros = otros.split()
    if otros and not reemplazar:
        sys.exit(f"Ya hay vhost activos con {DOMINIO}: {otros}. Decide antes y usa --reemplazar.")
    sftp = cli.open_sftp()
    sftp.putfo(io.BytesIO(VHOST_LOCAL.read_bytes().replace(b"\r\n", b"\n")), f"/tmp/{DOMINIO}.conf")
    sftp.close()
    ejecutar(cli, f"{s}install -m 644 /tmp/{DOMINIO}.conf {VHOST_REMOTO} && rm -f /tmp/{DOMINIO}.conf")
    ejecutar(cli, f"{s}a2enmod {' '.join(MODULOS)}")
    for o in otros:
        ejecutar(cli, f"{s}a2dissite {Path(o).name}")
    ejecutar(cli, f"{s}a2ensite {DOMINIO}")
    codigo, _ = ejecutar(cli, f"{s}apache2ctl configtest", comprobar=False)
    if codigo != 0:
        ejecutar(cli, f"{s}a2dissite {DOMINIO}", comprobar=False)
        for o in otros:
            ejecutar(cli, f"{s}a2ensite {Path(o).name}", comprobar=False)
        sys.exit("configtest falló: vhost desactivado y anteriores restaurados; Apache no se recargó.")
    ejecutar(cli, f"{s}systemctl reload apache2")


def humo(cli) -> None:
    ejecutar(cli, f"curl -sS -o /dev/null -w 'local %{{http_code}}\\n' http://127.0.0.1:{PUERTO_LOCAL}/", comprobar=False)
    ejecutar(cli, f"curl -sS http://127.0.0.1:{PUERTO_LOCAL}/api/health; echo", comprobar=False)
    ejecutar(cli, f"curl -sS -o /dev/null -w 'público %{{http_code}}\\n' https://{DOMINIO}/", comprobar=False)
    ejecutar(cli, f"curl -sS https://{DOMINIO}/api/health; echo", comprobar=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=["preflight", "app", "vhost", "humo"])
    p.add_argument("--ref", default="HEAD", help="ref de git a desplegar (app)")
    p.add_argument("--reemplazar", action="store_true", help="desactiva otros vhost con el mismo ServerName")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    datos = leer_env()
    usuario, host = destino(datos)
    if a.dry_run:
        print(f"[dry-run] {a.accion} en {usuario}@{host} por clave; ref={a.ref}; dir={DIR_REMOTO}")
        if a.accion == "app":
            print(f"[dry-run] .env remoto con claves: {[k for k in datos if not k.startswith('VPS_')]}")
        return
    cli = conectar_con_clave(usuario, host)
    s = sudo(usuario)
    try:
        {"preflight": lambda: preflight(cli, s),
         "app": lambda: app(cli, s, a.ref, datos),
         "vhost": lambda: vhost(cli, s, a.reemplazar),
         "humo": lambda: humo(cli)}[a.accion]()
    finally:
        cli.close()


if __name__ == "__main__":
    main()
