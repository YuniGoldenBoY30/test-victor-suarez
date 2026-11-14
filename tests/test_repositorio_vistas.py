import pytest

from app.db import abrir_conexion_lectura
from app.repositorio_vistas import RepositorioVistas


@pytest.fixture
def repo(db_prueba):
    return RepositorioVistas(lambda: abrir_conexion_lectura(db_prueba))


def test_ventas_por_mes_pais(repo):
    assert repo.ventas_por_mes_pais() == [
        {"mes": "2024-01-01", "pais": "España", "num_pedidos": 2, "total_ventas": 150.5},
        {"mes": "2024-02-01", "pais": "Francia", "num_pedidos": 1, "total_ventas": 75.0},
        {"mes": "2024-03-01", "pais": "España", "num_pedidos": 1, "total_ventas": 20.0},
    ]


def test_filtro_pais(repo):
    filas = repo.ventas_por_mes_pais("Francia")
    assert [f["pais"] for f in filas] == ["Francia"]


def test_filtro_pais_parametrizado(repo):
    assert repo.ventas_por_mes_pais("' OR 1=1 --") == []


def test_top_10_clientes(repo):
    filas = repo.top_10_clientes()
    assert filas[0] == {"cliente": "Ana", "num_pedidos": 2, "total_comprado": 150.5}
    assert {f["cliente"] for f in filas} == {"Ana", "Marie", "Luis"}
    luis = next(f for f in filas if f["cliente"] == "Luis")
    assert luis["total_comprado"] == 20.0  # excluye el cancelado
