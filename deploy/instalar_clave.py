"""Alta única de la clave SSH en el VPS. LO EJECUTA LA PERSONA RESPONSABLE, no un agente.

Usa la contraseña de `.env` (VPS_PROD_PASSWORD) solo para añadir
~/.ssh/id_ed25519_vps.pub a authorized_keys y luego comprueba que el acceso
por clave funciona. La contraseña nunca se imprime ni se guarda.

    python deploy/instalar_clave.py
"""
from __future__ import annotations

import shlex
import sys

from comun import CLAVE_PRIVADA, cliente_base, conectar_con_clave, destino, ejecutar, leer_env


def main() -> None:
    datos = leer_env()
    usuario, host = destino(datos)
    clave_publica = CLAVE_PRIVADA.with_suffix(".pub")
    if not clave_publica.exists():
        sys.exit(f"No existe {clave_publica}")
    linea = clave_publica.read_text(encoding="utf-8").strip()
    password = datos.get("VPS_PROD_PASSWORD")
    if not password:
        sys.exit("Falta VPS_PROD_PASSWORD en .env")

    cli = cliente_base()
    cli.connect(host, username=usuario, password=password, look_for_keys=False, allow_agent=False, timeout=15)
    q = shlex.quote(linea)
    ejecutar(
        cli,
        "umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
        f"(grep -qxF {q} ~/.ssh/authorized_keys || echo {q} >> ~/.ssh/authorized_keys) && "
        "chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys && echo clave instalada",
    )
    cli.close()

    cli = conectar_con_clave(usuario, host)
    ejecutar(cli, "echo acceso por clave OK")
    cli.close()


if __name__ == "__main__":
    main()
