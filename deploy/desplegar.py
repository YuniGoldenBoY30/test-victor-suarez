"""Despliegue en el VPS con paramiko (solo acceso por clave). Ver docs/DESPLIEGUE.md.

    python deploy/desplegar.py preflight            # solo lectura
    python deploy/desplegar.py app [--ref HEAD]     # sube la versión y docker compose up
    python deploy/desplegar.py placeholder          # página provisional en 127.0.0.1:8080
    python deploy/desplegar.py vhost [--reemplazar] # vhost de Apache + certificado Let's Encrypt
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
PLACEHOLDER = "project-ai-role-placeholder"
MODULOS = ("proxy", "proxy_http", "headers", "ssl", "rewrite", "remoteip")

# Ajustes que dependen del dominio publicado. Sin TRUSTED_HOSTS el backend responde
# 400 a todo lo que llega por el proxy (Host: test.zenixtech.ai). Un valor del .env
# local con el mismo nombre tiene prioridad.
AJUSTES_PRODUCCION = {
    "TRUSTED_HOSTS": f"{DOMINIO},localhost,127.0.0.1",
    "CORS_ORIGINS": f"https://{DOMINIO}",
    # Apache la sobrescribe con la IP real del cliente (mod_remoteip).
    "CABECERA_IP_CLIENTE": "X-Cliente-IP",
}


def env_produccion(datos: dict[str, str]) -> str:
    """.env del servidor: el local sin VPS_* más los ajustes del dominio que falten."""
    extra = {k: v for k, v in AJUSTES_PRODUCCION.items() if not datos.get(k)}
    return env_para_servidor(datos) + "".join(f"{k}={v}\n" for k, v in extra.items())


def preflight(cli, s: str) -> None:
    ejecutar(cli, "uname -a; . /etc/os-release && echo $PRETTY_NAME; whoami", comprobar=False)
    ejecutar(cli, "apache2 -v 2>&1 | head -1", comprobar=False)
    ejecutar(cli, f"{s}apache2ctl -M 2>/dev/null | grep -E '(proxy|proxy_http|headers|ssl|rewrite|remoteip)_module' || true", comprobar=False)
    ejecutar(cli, "ls /etc/apache2/sites-enabled/", comprobar=False)
    ejecutar(cli, f"grep -ril 'ServerName[[:space:]]*{DOMINIO}' /etc/apache2/sites-enabled/ || echo 'ningún vhost con {DOMINIO}'", comprobar=False)
    # Sin archivos, `grep -r` buscaría en el directorio actual: se comprueba antes.
    ejecutar(cli, f"f=$(grep -ril 'ServerName[[:space:]]*{DOMINIO}' /etc/apache2/sites-enabled/); "
                  "[ -n \"$f\" ] && grep -hE 'ProxyPass |DocumentRoot' $f | sort -u || true", comprobar=False)
    ejecutar(cli, f"ls /etc/letsencrypt/live/{DOMINIO}/fullchain.pem 2>/dev/null || echo 'sin certificado para {DOMINIO}'", comprobar=False)
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
    print(f"sftp .env (sin VPS_*, con ajustes de {DOMINIO}) -> {DIR_REMOTO}/shared/.env")
    with sftp.open("/tmp/project-ai-role.env", "w") as f:
        f.chmod(0o600)  # antes de escribir la clave de NVIDIA
        f.write(env_produccion(datos).encode("utf-8"))
    sftp.close()
    ejecutar(cli, f"{s}install -m 600 /tmp/project-ai-role.env {DIR_REMOTO}/shared/.env && rm -f /tmp/project-ai-role.env")
    ejecutar(cli, f"{s}tar -xzf {remoto_tar} -C {rel} && rm -f {remoto_tar} && {s}ln -sfn {DIR_REMOTO}/shared/.env {rel}/.env")
    ejecutar(cli, f"{s}ln -sfn {rel} {DIR_REMOTO}/current")
    ejecutar(cli, f"{s}docker rm -f {PLACEHOLDER} >/dev/null 2>&1 || true")
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
    # Copia del vhost actual: si el nuevo no pasa configtest se restaura el anterior
    # y el sitio sigue sirviéndose (en vez de caer al vhost por defecto).
    copia = f"{VHOST_REMOTO}.anterior"
    habia_anterior = ejecutar(cli, f"{s}cp -p {VHOST_REMOTO} {copia}", comprobar=False)[0] == 0
    ejecutar(cli, f"{s}install -m 644 /tmp/{DOMINIO}.conf {VHOST_REMOTO} && rm -f /tmp/{DOMINIO}.conf")
    ejecutar(cli, f"{s}a2enmod {' '.join(MODULOS)}")
    for o in otros:
        ejecutar(cli, f"{s}a2dissite {Path(o).name}")
    ejecutar(cli, f"{s}a2ensite {DOMINIO}")
    codigo, _ = ejecutar(cli, f"{s}apache2ctl configtest", comprobar=False)
    if codigo != 0:
        if habia_anterior:
            ejecutar(cli, f"{s}mv -f {copia} {VHOST_REMOTO}", comprobar=False)
        else:
            ejecutar(cli, f"{s}a2dissite {DOMINIO}", comprobar=False)
        for o in otros:
            ejecutar(cli, f"{s}a2ensite {Path(o).name}", comprobar=False)
        ejecutar(cli, f"{s}apache2ctl configtest", comprobar=False)
        sys.exit("configtest falló: se restauró la configuración anterior; Apache no se recargó.")
    ejecutar(cli, f"{s}rm -f {copia}", comprobar=False)
    ejecutar(cli, f"{s}systemctl reload apache2")
    cert = f"/etc/letsencrypt/live/{DOMINIO}/fullchain.pem"
    if ejecutar(cli, f"test -f {cert}", comprobar=False)[0] != 0:
        # La cuenta de certbot ya existe en el servidor (otros dominios).
        ejecutar(cli, f"{s}mkdir -p /var/www/html/.well-known/acme-challenge")
        ejecutar(cli, f"{s}certbot certonly --webroot -w /var/www/html -d {DOMINIO} --non-interactive --keep-until-expiring", timeout=300)
        ejecutar(cli, f"{s}apache2ctl configtest && {s}systemctl reload apache2")


def placeholder(cli, s: str) -> None:
    """Página provisional en 127.0.0.1:8080 para probar la cadena antes de tener la app."""
    html = "<!doctype html><meta charset=utf-8><title>project-ai-role</title><h1>project-ai-role: despliegue de prueba</h1>"
    ejecutar(cli, f"{s}mkdir -p {DIR_REMOTO}/placeholder && printf '%s' '{html}' | {s}tee {DIR_REMOTO}/placeholder/index.html >/dev/null")
    ejecutar(cli, f"{s}docker rm -f {PLACEHOLDER} >/dev/null 2>&1; {s}docker run -d --name {PLACEHOLDER} --restart unless-stopped "
                  f"-p 127.0.0.1:{PUERTO_LOCAL}:80 -v {DIR_REMOTO}/placeholder:/usr/share/nginx/html:ro nginx:alpine")
    ejecutar(cli, f"sleep 2; curl -fsS http://127.0.0.1:{PUERTO_LOCAL}/; echo")


def humo(cli) -> None:
    ejecutar(cli, f"curl -sS -o /dev/null -w 'local %{{http_code}}\\n' http://127.0.0.1:{PUERTO_LOCAL}/", comprobar=False)
    ejecutar(cli, f"curl -sS http://127.0.0.1:{PUERTO_LOCAL}/api/health; echo", comprobar=False)
    ejecutar(cli, f"curl -sS -o /dev/null -w 'público %{{http_code}}\\n' https://{DOMINIO}/", comprobar=False)
    ejecutar(cli, f"curl -sS https://{DOMINIO}/api/health; echo", comprobar=False)
    ejecutar(cli, f"curl -sSI https://{DOMINIO}/ | grep -iE '^(strict-transport|content-security|x-frame|x-content|referrer|permissions)' "
                  "|| echo 'sin cabeceras de seguridad en el HTML'", comprobar=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=["preflight", "placeholder", "app", "vhost", "humo"])
    p.add_argument("--ref", default="HEAD", help="ref de git a desplegar (app)")
    p.add_argument("--reemplazar", action="store_true", help="desactiva otros vhost con el mismo ServerName")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    datos = leer_env()
    usuario, host = destino(datos)
    if a.dry_run:
        print(f"[dry-run] {a.accion} en {usuario}@{host} por clave; ref={a.ref}; dir={DIR_REMOTO}")
        if a.accion == "app":
            claves = [linea.split("=", 1)[0] for linea in env_produccion(datos).splitlines()]
            print(f"[dry-run] .env remoto con claves: {claves}")
        return
    cli = conectar_con_clave(usuario, host)
    s = sudo(usuario)
    try:
        {"preflight": lambda: preflight(cli, s),
         "app": lambda: app(cli, s, a.ref, datos),
         "placeholder": lambda: placeholder(cli, s),
         "vhost": lambda: vhost(cli, s, a.reemplazar),
         "humo": lambda: humo(cli)}[a.accion]()
    finally:
        cli.close()


if __name__ == "__main__":
    main()
