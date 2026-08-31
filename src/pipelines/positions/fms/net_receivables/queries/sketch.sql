-- account receivables
CREATE PROCEDURE [FMS].[R_CONEX3_CxC]
    @IdSecuencialFecha FMS.IdRegistro
AS
BEGIN
    SELECT 
        COD_FOND = FP.CodigoFondo,
        SIM_MONE = M.Simbolo,
        SLD_FINA = isnull(sum(abs(CCP.Importe)),0)
    FROM FMS.CuentaCobrarPagar AS CCP
    INNER JOIN FMS.FondoPension AS FP ON FP.IdFondo = CCP.IdFondo
    INNER JOIN FMS.MOneda AS M ON M.IdMoneda = CCP.IdMoneda
    INNER JOIN FMS.Indicador AS T ON T.Id = CCP.IndCobrarPagar
    WHERE   T.IdINdicador = 1 AND
            CCP.FlgActivo = 1 AND
            (CCP.IndEstado = 4168 OR (CCP.IndEstado = 4169 AND CCP.IdSecuencialFechaLiquidacionReal > @IdSecuencialFecha)) AND
            CCP.IdSecuencialFechaOperacion <= @IdSecuencialFecha
    GROUP BY    FP.CodigoFondo,
                M.Simbolo
    ORDER BY FP.CodigoFOndo,
                M.Simbolo
    

-- account payables
CREATE PROCEDURE [FMS].[R_CONEX3_CxC]
    @IdSecuencialFecha FMS.IdRegistro
AS
BEGIN
    SELECT 
        COD_FOND = FP.CodigoFondo,
        SIM_MONE = M.Simbolo,
        SLD_FINA = isnull(sum(abs(CCP.Importe)),0)
    FROM FMS.CuentaCobrarPagar AS CCP
    INNER JOIN FMS.FondoPension AS FP ON FP.IdFondo = CCP.IdFondo
    INNER JOIN FMS.MOneda AS M ON M.IdMoneda = CCP.IdMoneda
    INNER JOIN FMS.Indicador AS T ON T.Id = CCP.IndCobrarPagar
    WHERE   T.IdINdicador = 2 AND
            CCP.FlgActivo = 1 AND
            (CCP.IndEstado = 4168 OR (CCP.IndEstado = 4169 AND CCP.IdSecuencialFechaLiquidacionReal > @IdSecuencialFecha)) AND
            CCP.IdSecuencialFechaOperacion <= @IdSecuencialFecha
    GROUP BY    FP.CodigoFondo,
                M.Simbolo
    ORDER BY FP.CodigoFOndo,
                M.Simbolo