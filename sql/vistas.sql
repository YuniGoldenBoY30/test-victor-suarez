CREATE OR REPLACE VIEW ventas_por_mes_pais AS
SELECT
    CAST(date_trunc('month', fecha) AS DATE) AS mes,
    pais,
    COUNT(*) AS num_pedidos,
    SUM(importe) AS total_ventas
FROM pedidos
WHERE estado <> 'cancelado'
GROUP BY 1, 2
ORDER BY 1, 2;

CREATE OR REPLACE VIEW top_10_clientes AS
SELECT
    cliente,
    COUNT(*) AS num_pedidos,
    SUM(importe) AS total_comprado
FROM pedidos
WHERE estado <> 'cancelado'
GROUP BY cliente
ORDER BY total_comprado DESC
LIMIT 10;
