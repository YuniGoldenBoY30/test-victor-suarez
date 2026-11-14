"""Utilidades compartidas por los scripts de despliegue (paramiko)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

RAIZ = Path(__file__).resolve().parent.parent
RUTA_ENV = Path(os.environ.get("DEPLOY_ENV", RAIZ / ".env"))  # DEPLOY_ENV para worktrees
CLAVE_PRIVADA = Path.home() / ".ssh" / "id_ed25519_vps"
PREFIJO_SOLO_LOCAL = "VPS_"


def leer_env(ruta: Path = RUTA_ENV) -> dict[str, str]:
    """Lee un .env sencillo (CLAVE=valor). No expande variables."""
    if not ruta.exists():
        sys.exit(f"No existe {ruta}")
    datos: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        datos[clave.strip()] = valor.strip().strip('"').strip("'")
    return datos


def env_para_servidor(datos: dict[str, str]) -> str:
    """Contenido del .env de ejecución: todo menos las credenciales del VPS."""
    return "".join(
        f"{k}={v}\n" for k, v in datos.items() if not k.startswith(PREFIJO_SOLO_LOCAL)
    )


def destino(datos: dict[str, str]) -> tuple[str, str]:
    try:
        return datos["VPS_PROD_USER"], datos["VPS_PROD_HOST"]
    except KeyError as e:
        sys.exit(f"Falta {e.args[0]} en .env")


def cliente_base() -> paramiko.SSHClient:
    cli = paramiko.SSHClient()
    cli.load_system_host_keys()
    known = Path.home() / ".ssh" / "known_hosts"
    if known.exists():
        cli.load_host_keys(str(known))
    # Host desconocido: rechazar. Se añade antes con `ssh-keyscan` o un primer `ssh`.
    cli.set_missing_host_key_policy(paramiko.RejectPolicy())
    return cli


def conectar_con_clave(usuario: str, host: str, clave: Path = CLAVE_PRIVADA) -> paramiko.SSHClient:
    """Conexión solo por clave: nunca usa contraseña."""
    if not clave.exists():
        sys.exit(f"No existe la clave {clave}")
    cli = cliente_base()
    try:
        cli.connect(
            host,
            username=usuario,
            key_filename=str(clave),
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
        )
    except paramiko.AuthenticationException:
        sys.exit(f"El VPS rechaza la clave {clave.name}. Ejecuta antes: python deploy/instalar_clave.py")
    except (TimeoutError, OSError) as e:
        sys.exit(f"Sin conexión con {host}:22 ({e}). Reintenta en unos minutos.")
    except paramiko.SSHException as e:
        sys.exit(f"SSH: {e}. Si el host es desconocido, añádelo con: ssh-keyscan {host} >> ~/.ssh/known_hosts")
    return cli


def ejecutar(cli: paramiko.SSHClient, comando: str, *, comprobar: bool = True, timeout: int = 900) -> tuple[int, str]:
    """Ejecuta en remoto, muestra la salida y devuelve (código, salida)."""
    print(f"$ {comando}", flush=True)
    _, out, err = cli.exec_command(comando, timeout=timeout, get_pty=False)
    salida = out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")
    codigo = out.channel.recv_exit_status()
    if salida.strip():
        print(salida.rstrip(), flush=True)
    if comprobar and codigo != 0:
        sys.exit(f"Falló (código {codigo}): {comando}")
    return codigo, salida


def sudo(usuario: str) -> str:
    return "" if usuario == "root" else "sudo -n "


os.environ.setdefault("PYTHONIOENCODING", "utf-8")
