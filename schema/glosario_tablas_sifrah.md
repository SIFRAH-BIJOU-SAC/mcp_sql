# Glosario de Datos · SIFRAH_DWH

> **Propósito:** Diccionario único y canónico de todas las tablas del Data Warehouse `[SIFRAH_DWH].[dbo]`, para estandarizar nombres, evitar errores de escritura/join y servir de referencia obligatoria antes de escribir cualquier query o vista.
>
> **Motor:** SQL Server (T-SQL). **Esquema base:** `[SIFRAH_DWH].[dbo]`.
>
> **Estado:** ✦ Primer approach para revisión de Daniel. Los tipos de dato están **inferidos** por el nombre/uso y deben confirmarse contra `INFORMATION_SCHEMA.COLUMNS`.
>
> **Última actualización:** 2026-08-19

---

## 0. Índice y modelo de datos

### 0.1 Tablas del modelo

- ✦ **Dimensiones:** `DIM_PRODUCTO`, `DIM_PROMOCIONES`, `DIM_TIEMPO`, `DIM_CLIENTE`, `DIM_TIPODOCUMENTO`, `DIM_TIENDA` *(pendiente de documentar — ver §9)*.
- ✦ **Hechos:** `FACT_VENTAS`, `FACT_KARDEX`.

### 0.2 Llaves y relaciones (esquema estrella)

- ✦ `FACT_VENTAS.Codigo_Producto` → `DIM_PRODUCTO.Codigo_Producto`
- ✦ `FACT_VENTAS.Codigo_Cliente` → `DIM_CLIENTE.Codigo_Cliente`
- ✦ `FACT_VENTAS.Tiempo_Id` → `DIM_TIEMPO.Tiempo_Id`
- ✦ `FACT_VENTAS.Codigo_Promocion` → `DIM_PROMOCIONES.Codigo_Promocion`
- ✦ `FACT_VENTAS.Codigo_Tienda` → `DIM_TIENDA.Codigo_Tienda`
  Todos son codigos de tienda, sin embargo es importante resaltar lo siguiente:
- 0 -> Almacen
- 1 -> SIFRAH Ecommerce
- 3 -> SIFRAH Ecommerce Devoluciones
- 27 -> Almacen diferencias
- 28 -> Almacen logsitica inversa
- 29 -> Almacen sala de muestras
- 9996 -> Almacen nuevo
- 9997 -> Almacen APERTURAMAS
- 9998 -> Almacen mermas
  Filtrar de acuerdo al anallisis. Para analizar ecommerce, usar el 3.
  Para hacer analisis de forecasting, filtrar todo lo que es almacén y tambien el 3.
- ✦ `FACT_KARDEX.Codigo_Producto` → `DIM_PRODUCTO.Codigo_Producto`
- ✦ `FACT_KARDEX.Tiempo_Id` → `DIM_TIEMPO.Tiempo_Id`
- ✦ `FACT_KARDEX.Codigo_Tienda` → `DIM_TIENDA.Codigo_Tienda` *(DIM_TIENDA pendiente)*
- ✦ `DIM_CLIENTE.Tipo_Documento` / `Tipo_Documento_V2` se relacionan conceptualmente con `DIM_TIPODOCUMENTO` *(confirmar llave real: `Codigo_TipoDocumento`)*.

Los valores de Tipo_Documento son las siguientes:
Codigo_TipoDocumento	Tipo_Documento
1	TK-FACTURA
2	BOLETA DE VENTA ELECTRONICA
3	TK-NOTA CREDITO
4	FACTURA
5	BOLETA
6	NOTA DE CREDITO
7	NOTADEBITO
8	TK-NOTADEBITO
9	RECIBO DE GIFTCARD

Para el caso de desarrollar algún forecasting, es bueno solo concentrarse en los tipos 2, 4 y 5; no considerando devoluciones ni nota de credito ni recibos de gitfcard, excepto los casos que se solicite este analisis.

### 0.3 Convenciones de nombres detectadas

- ✦ Prefijos: `DIM_` para dimensiones, `FACT_` para hechos.
- ✦ Llaves de negocio nombradas `Codigo_*`; llave de tiempo como `Tiempo_Id`.
- ✦ Sufijo `_V2` = versión revisada/actual del atributo (conviven con la versión original).
- ✦ Prefijo `Flag_` = indicador booleano (0/1 o True/False — **confirmar dominio**).
- ✦ Ojo con acentos y `ñ` en nombres de columna: `[Año]`, `[SemanaAño]` y valores con mojibake (`NIÃ‘AS` por `NIÑAS`) — ver §8.

---

## 1. DIM_PRODUCTO

Dimensión de producto (SKU). **Grano:** un registro por `Codigo_Producto`.

- ✦ **`Codigo_Producto`** — 🔑 **PK**. Código único del SKU. Llave de join con `FACT_VENTAS` y `FACT_KARDEX`.
- ✦ **`Codigo_Barra`** — Código de barras (EAN) del producto.
- ✦ **`Codigo_Proveedor`** — Código del proveedor del producto.
- ✦ **`Descripcion_Producto`** — Descripción/nombre comercial del SKU. Usado como *fallback* de `Familia2` cuando la familia queda vacía.
- ✦ **`Nombre_Linea`** — Línea de producto (nivel 1 de jerarquía). Valores conocidos: `BISUTERIA`, `BELLEZA`, `PROMOCIONAL`, `REGALERIA`, `RELOJ`, `ROPA`, `ACCESORIO DE CABELLO`, `CARTERAS Y MOCHILAS`, `COMPLEMENTOS DE VESTIR`.
- ✦ **`Nombre_Familia`** — Familia de producto (nivel 2). Incluye casos compuestos como `COLLAR + ARETE`.
- ✦ **`Nombre_SubFamilia`** — Subfamilia (nivel 3). Puede venir vacía o con mojibake (`NIÃ‘AS`).
- ✦ **`Personalidad`** — Atributo de estilo/personalidad del producto (ej. `BASICO`, `CASUAL`, `MODA`, `PREMIUM`). Base de `Personalidad2`.
- ✦ **`Tipo_Producto`** — Clasificación de tipo de producto: 'ITEM','SERVICIO','COMBO', 'GIFTCARD' y (vacion en SQL).
- ✦ **`Tipo_Mercaderia`** — Clasificación de tipo de mercadería.
- ✦ **`Proveedor`** — Nombre del proveedor (texto).
- ✦ **`Color`** — Color del producto.
- ✦ **`Talla`** — Talla del producto.
- ✦ **`Modelo`** — Modelo del producto.
- ✦ **`Tendencia`** — Indicador/clasificación de tendencia.
- ✦ **`Periodo_Compra`** — Periodo en que se compró el producto.
- ✦ **`Temporada`** — Temporada asociada al producto.
- ✦ **`Ocasion`** — Ocasión de uso (Grande, Intermedio, pequeño, unico).
- ✦ **`Pais_Origen`** — País de origen del producto. Principalmente 'CHINA', luego: 'LIMA', 'PERU', 'COLOMBIA', 'CANADA', (Vacion en SQL), 'INDIA'.
- ✦ **`Fecha_Traslado`** — Fecha de traslado. Tipo: '17.3.Mar'. No todos los productos lo tienen. Significa cuando un producto va a ser estrenado.
- ✦ **`Material_2`** — Material del producto. No existe la version 1
- ✦ **`Rango_Precio`** — Rango de precio. Hay lineas que no tienen todos los rangos de precios.

| Rango de precio      | Cantidad de elementos |
| -------------------- | --------------------: |
| `<0 ; 6.9>`        |                  2056 |
| `<6.9 ; 9.9>`      |                  5835 |
| `<9.9 ; 12.9>`     |                  6921 |
| `<12.9 ; 14.9>`    |                  5655 |
| `<14.9 ; 16.9>`    |                  4744 |
| `<16.9 ; 19.9>`    |                  5743 |
| `<19.9 ; 24.9>`    |                  5490 |
| `<24.9 ; 29.9>`    |                  5056 |
| `<29.9 ; 34.9>`    |                  2172 |
| `<34.9 ; 39.9>`    |                  3416 |
| `<39.9 ; 49.9>`    |                  2602 |
| `<49.9 ; 59.9>`    |                   739 |
| `<59.9 ; 69.9>`    |                   812 |
| `<69.9 ; 79.9>`    |                   941 |
| `<79.9 ; 89.9>`    |                  1073 |
| `<89.9 ; 99.9>`    |                   822 |
| `<99.9 ; 109.9>`   |                   374 |
| `<109.9 ; 119.9>`  |                   320 |
| `<119.9 ; a más>` |                  1036 |
| Sin rango(' ')       |        **5616** |

- ✦ **`Precio_Vta_Actual`** — Precio de venta vigente (numérico/decimal).
  Ejemplo:

| Precio vta actual | Cantidad |
| ----------------: | -------: |
|          14.90000 |     5421 |
|          12.90000 |     5153 |
|           0.00000 |     4507 |
|          16.90000 |     4494 |
|          24.90000 |     3907 |
|                   |          |

- ✦ **`Costo_Promedio_Actual`** — Costo promedio vigente (numérico/decimal).
- ✦ **`Ruta_Imagen`** — Ruta/URL de la imagen del producto.
- ✦ **`Flag_Mercaderia`** — Indicador de mercadería: 'Importado', 'Nacional'
- ✦ **`Estado_Maquila`** — Estado de maquila del producto: 'Sin maquila', 'Con maquila'.
- ✦ **`Flag_Tipo_Producto`** — Indicador de tipo de producto. Tipos:`MERCADERIA`,`SUMINISTROS - ACONDICIONAMIENTO`,`LICENCIAS`,`SUMINISTROS - DESPACHO`,`SUMINISTROS - CONSUMO`,`SERVICIOS`,`ACTIVOS`,`TECNOLOGIA`,`GIFTCARDS` y `(vacio en SQL)`

---

## 2. DIM_PROMOCIONES

Dimensión de promociones/campañas. **Grano:** un registro por `Codigo_Promocion`. Una debilidad es que, los periodos activos se sobreescribien en la fecha inicio y fecha_fin. Es decir, no mantiene un historico. Para preveer esto, te he adjuntado algunas cons

- ✦ **`Codigo_Promocion`** — 🔑 **PK**. Código único de la promoción. Join con `FACT_VENTAS.Codigo_Promocion`.
- ✦ **`Estado`** — Estado de la promoción (ej. activa/inactiva — confirmar dominio).
- ✦ **`Fecha_Inicio`** — Fecha de inicio de vigencia.
- ✦ **`Fecha_Fin`** — Fecha de fin de vigencia.
- ✦ **`Tipo_Promocion`** — Tipo de promoción (ej. descuento, 3x2, regalo).
- ✦ **`Nombre_Promocion`** — Nombre descriptivo de la promoción.
- ✦ **`Categoria_Promocion`** — Categoría/agrupador de la promoción.
  -- Existen las siguientes categorias:

---

Categoria_Promocion
CAPTACION -> Se busca atraer nuevos clientes.
ACCION -> Alguna acción para obtener algún resultado. Por ejemplo, hacer ofertas para licuar inventario.
NULL -> Promoción NULL.
FIDELIZACION ->
ROTACION -> Si no me equivoco, trae descuentos agresivos.
FRECUENCIA -> Para aumentar la compra.

GASTOS -> Pago a influencers con giftcard, 40% de descuento para colaboradores de la empresa, entre otros tipos.
ACCIONES -> Lo mismo que accion
-------------------------------

Es necesario unir ACCION  y ACCIONES para hacer las consultas.
--------------------------------------------------------------

## 3. DIM_TIEMPO

Dimensión de calendario. **Grano:** un registro por día (`Tiempo_Id`).

- ✦ **`Tiempo_Id`** — 🔑 **PK**. Identificador de fecha (surrogate/entero). Join con `FACT_VENTAS.Tiempo_Id` y `FACT_KARDEX.Tiempo_Id`.
- ✦ **`Fecha`** — Fecha calendario (DATE).
- ✦ **`Dia`** — Día del mes (1–31).
- ✦ **`Mes`** — Número de mes (1–12).
- ✦ **`Año`** — Año (⚠️ nombre con acento: usar `[Año]`).
- ✦ **`NombreMes`** — Nombre del mes (texto).
- ✦ **`NombreDia`** — Nombre del día de la semana (texto; **confirmar idioma/escritura** para flags de fin de semana).
- ✦ **`SemanaAño`** — Número de semana del año (⚠️ acento: `[SemanaAño]`).
- ✦ **`Trimestre`** — Número de trimestre (1–4).
- ✦ **`Semestre`** — Número de semestre (1–2).
- ✦ **`Anio_Mes`** — Periodo AAAAMM o AAAA-MM (confirmar formato).
- ✦ **`Trimestre_Tx`** — Trimestre como texto (ej. `Q1`).
- ✦ **`SemanaMes_Num`** — Número de semana dentro del mes.
- ✦ **`SemanaMes_Tx`** — Semana del mes como texto.
- ✦ **`TEMPORADA`** — Temporada comercial del periodo (mayúsculas en origen).

---

## 4. DIM_CLIENTE

Dimensión de cliente. **Grano:** un registro por `Codigo_Cliente`. Contiene atributos de segmentación (RFM), contactabilidad y geografía.

### 4.1 Identificación

- ✦ **`Codigo_Cliente`** — 🔑 **PK**. Código único del cliente. Join con `FACT_VENTAS.Codigo_Cliente`.
- ✦ **`Codigo_Tienda`** — Tienda de registro/origen del cliente.
- ✦ **`Documento_Identidad`** — Número de documento.
- ✦ **`Tipo_Documento`** — Tipo de documento (versión original). Relacionado con `DIM_TIPODOCUMENTO`.
- ✦ **`Tipo_Documento_V2`** — Tipo de documento (versión revisada/actual).
- ✦ **`RazonSocial`** — Razón social (clientes empresa).

### 4.2 Datos demográficos

- ✦ **`Nombre`** — Nombre del cliente.
- ✦ **`Apellido`** — Apellido del cliente.
- ✦ **`Genero`** — Género.
- ✦ **`Fecha_Nacimiento`** — Fecha de nacimiento.
- ✦ **`Edad`** — Edad (numérica).
- ✦ **`Rango_Edad`** — Bucket de edad.
- ✦ **`Rango_Generacional`** — Rango generacional (ej. Millennial, Z).
- ✦ **`Descripcion_Generacional`** — Descripción del rango generacional.

### 4.3 Contactabilidad y consentimiento

- ✦ **`Correo_Electronico`** — Email principal.
- ✦ **`Correo_Electronico2`** — Email secundario.
- ✦ **`Celular`** — Número de celular.
- ✦ **`Acepta_Email`** — Consentimiento de email.
- ✦ **`Flag_Email`** — Indicador de contactabilidad por email.
- ✦ **`Flag_SMS`** — Indicador de contactabilidad por SMS.
- ✦ **`Flag_Whatsapp`** — Indicador de contactabilidad por WhatsApp.
- ✦ **`Flag_Total`** — Indicador consolidado de contactabilidad *(confirmar lógica)*.
- ✦ **`Participa_Recompensas`** — Participa en programa de recompensas/fidelización.

### 4.4 Geografía

- ✦ **`Direccion`** — Dirección.
- ✦ **`Ciudad`** — Ciudad.
- ✦ **`Departamento`** — Departamento (Perú).
- ✦ **`Codigo_Postal`** — Código postal.
- ✦ **`Id_Pais`** — Identificador de país.
- ✦ **`Telefono_Direccion`** — Teléfono asociado a la dirección.
- ✦ **`Ubigeo`** — Código UBIGEO (ubicación geográfica INEI-Perú).
- ✦ **`Latitude`** — Latitud.
- ✦ **`Longitude`** — Longitud.

### 4.5 Registro y segmentación

- ✦ **`Fecha_Registro`** — Fecha de alta del cliente.
- ✦ **`Tiempo_Id_Registro`** — `Tiempo_Id` del registro (join con `DIM_TIEMPO`).
- ✦ **`Correo_Valido_RFM`** — Indicador de email válido para análisis RFM.
- ✦ **`identidad_valida_RFM`** — Indicador de identidad válida para RFM (⚠️ minúsculas en origen).
- ✦ **`segmento_past_descrip`** — Descripción del segmento RFM anterior (⚠️ minúsculas).
- ✦ **`segmento_act_descrip`** — Descripción del segmento RFM actual (⚠️ minúsculas).
- ✦ **`Tipo_Cliente`** — Clasificación de cliente (versión original).
- ✦ **`Tipo_Cliente_V2`** — Clasificación de cliente (versión revisada/actual).
- ✦ **`Es_Ocasional`** — Indicador de cliente ocasional.

---

## 5. DIM_TIPODOCUMENTO

Dimensión catálogo de tipos de documento de identidad. **Grano:** un registro por tipo.

- ✦ **`Codigo_TipoDocumento`** — 🔑 **PK** (en origen aparece aliasado como `[Key]`). Join hacia `DIM_CLIENTE`.
- ✦ **`Tipo_Documento`** — Descripción del tipo de documento (ej. DNI, RUC, CE, Pasaporte).

---

## 6. FACT_VENTAS

Tabla de hechos de ventas. **Grano:** línea de venta = producto dentro de un documento (ticket/boleta/factura). Es la tabla central del modelo.

### 6.1 Llaves foráneas (dimensiones)

- ✦ **`Codigo_Empresa`** — Empresas. Tienen la siguiente dimensión (DIM_EMPRESA):
  Codigo_Empresa	Nombre_Empresa
  1	SIFRAH BIJOU S.A.C
  2	AXTRACORP S.A.C
  3	VILLA MBC LOGISTICA S.A.C
  4	CHM COMPANY S.A.C
  1000	NO MAPEADO
- ✦ **`Codigo_Tienda`** — 🔗 FK a `DIM_TIENDA`.
- ✦ **`Codigo_Empleado`** — Empleado/vendedor (dimensión no documentada — confirmar).
- ✦ **`Codigo_Cliente`** — 🔗 FK a `DIM_CLIENTE`.
- ✦ **`Codigo_Producto`** — 🔗 FK a `DIM_PRODUCTO`.
- ✦ **`Codigo_Antiguedad`** — Antigüedad DEL PRODUCTO
- ✦ **`Tiempo_Id`** — 🔗 FK a `DIM_TIEMPO`.
- ✦ **`Codigo_Promocion`** — 🔗 FK a `DIM_PROMOCIONES` (a nivel línea de producto).

### 6.2 Documento / transacción

- ✦ **`Nro_Documento`** — Número de documento de venta. Con `Codigo_Tienda` forma el ticket único (`Ticket_Key = Codigo_Tienda-Nro_Documento`).
- ✦ **`Id_tipdocventa`** — Tipo de documento de venta (boleta/factura/nota — confirmar catálogo).
- ✦ **`Hora_Venta`** — Hora de la venta.

### 6.3 Medidas de venta e IGV

- ✦ **`Vta_SinIgv_Prod`** — Venta sin IGV del producto (base imponible).
- ✦ **`Vta_Igv_Prod`** — Venta con IGV del producto.
- ✦ **`total_unid_vend_prod`** — Unidades vendidas del producto.
- ✦ **`ppu_prod`** — Precio por unidad del producto (price per unit).

### 6.4 Costo y margen

- ✦ **`cost_vent_total_prod`** — Costo de venta total del producto.
- ✦ **`cost_prom_unid_prod`** — Costo promedio unitario del producto.
- ✦ **`marg_bru_total_prod`** — Margen bruto total del producto.
- ✦ **`marg_bru_porc_prod`** — Margen bruto porcentual del producto.

### 6.5 Precio lista ("precio blanco") y descuentos

- ✦ **`vent_pre_list_prod`** — Venta a precio de lista con IGV ("precio blanco").
- ✦ **`vent_pre_list_sinigv_prod`** — Venta a precio de lista sin IGV.
- ✦ **`total_dscto_sinigv_prod`** — Descuento total sin IGV.
- ✦ **`total_dscto_igv_prod`** — Descuento total con IGV.
- ✦ **`Dscto_Producto`** — Descuento a nivel producto/línea.
- ✦ **`Dscto_Documento`** — Descuento a nivel documento/ticket.

### 6.6 Promoción y cupón (a nivel documento)

- ✦ **`Promo_Documento`** — Promoción aplicada a nivel documento.
- ✦ **`Codigo_Promocion_Documento`** — Código de promoción a nivel documento (distinto de `Codigo_Promocion` de línea).
- ✦ **`CouponNo`** — Número de cupón.
- ✦ **`CouponCode`** — Código de cupón.
- ✦ **`Id_Segmento`** — Segmento asociado a la venta *(confirmar catálogo)*.

---

## 7. FACT_KARDEX

Tabla de hechos de inventario (kardex). **Grano:** stock/movimiento acumulado por `Tiempo_Id` × `Codigo_Tienda` × `Codigo_Producto`.

- ✦ **`Tiempo_Id`** — 🔗 FK a `DIM_TIEMPO`.
- ✦ **`Fecha`** — Fecha del corte (redundante con `DIM_TIEMPO.Fecha`).
- ✦ **`Codigo_Tienda`** — 🔗 FK a `DIM_TIENDA`.
- ✦ **`Codigo_Producto`** — 🔗 FK a `DIM_PRODUCTO`.
- ✦ **`Compras_Iniciales_Acumulados`** — Compras iniciales acumuladas.
- ✦ **`Entradas_Acumulados`** — Entradas de mercadería acumuladas.
- ✦ **`Salidas_Acumuladas`** — Salidas acumuladas (no venta).
- ✦ **`Ajustes_Acumulados`** — Ajustes de inventario acumulados.
- ✦ **`Ventas_Acumuladas`** — Unidades vendidas acumuladas.
- ✦ **`Stock_Calculado`** — Stock calculado (compras/entradas − salidas − ventas ± ajustes).
- ✦ **`Stock_Final`** — Stock final reportado. *(Comparar contra `Stock_Calculado` para detectar descuadres).*

---

## 8. Capa de negocio · columnas derivadas en vistas

Estas columnas **no existen físicamente**. Se documentan aquí para que se usen de forma consistente y no se redefinan distinto en cada query.

### 8.1 Jerarquía normalizada de producto (traducción del DAX)

- ✦ **`Personalidad2`** — Normaliza `DIM_PRODUCTO.Personalidad`. Si `Nombre_Linea = 'BISUTERIA'` y la personalidad es `BASICO`/nula/vacía → `PREMIUM`; si no es bisutería → `BASICO`.
- ✦ **`Familia2`** — Normaliza `Nombre_Familia`. Reglas: `PROMOCIONAL`/`REGALERIA`/`BELLEZA` heredan de la línea; `COLLAR + ARETE` → `COLLAR`; si queda vacío → `Descripcion_Producto`.
- ✦ **`SubFamilia2`** — Normaliza `Nombre_SubFamilia`. Líneas de accesorios/ropa → `DAMAS`; `NIÑAS`/`NIÃ‘AS` → `NINAS`; vacío → `DAMAS`.

### 8.2 Flags y clasificaciones de tienda-mes

- ✦ **`Dias_Apertura` / `#Dias_Apertura_Tienda` / `#Dias_Apertura_Tienda_Mes`** — Días con venta de la tienda en el mes (`COUNT(DISTINCT Tiempo_Id)`; en la vista diaria vía `DENSE_RANK`).
- ✦ **`Flag_Tienda_Completas`** — `'True'` si la tienda abrió ≥ 25 días en el mes; si no `'False'`.
- ✦ **`DETALLE25`** — Clasificación por completitud en los 12 meses de 2025: `Aper2026`, `Aper2025`, `BASE` (12 meses completos), `BASE_REV` (con historia pero incompleta).
- ✦ **`DETALLE18M`** — Igual que `DETALLE25` pero sobre los últimos 18 meses corridos (ancla = último mes con data).

### 8.3 Calendario y fin de semana

- ✦ **`Dia_Semana_Num`** — Día de semana determinista 1=Lun … 7=Dom (`(DATEDIFF(DAY,'1900-01-01',Fecha)%7)+1`), independiente de idioma/`DATEFIRST`.
- ✦ **`Flag_FinSemana_VieDom`** — 1 si `Dia_Semana_Num ∈ {5,6,7}` (Vie-Sáb-Dom).
- ✦ **`Flag_FinSemana_SabDom`** — 1 si `Dia_Semana_Num ∈ {6,7}` (Sáb-Dom).

### 8.4 Ticket y segmentación promocional

- ✦ **`Ticket_Key`** — `CONCAT(Codigo_Tienda,'-',Nro_Documento)`. Identificador de ticket único; base de `Num_Tickets`.
- ✦ **`Segmento_Promo`** — `ARETE_MODA` (BISUTERIA + Familia2=ARETE + Personalidad2=MODA), `ACERO_CASUAL` (BISUTERIA + Personalidad2=CASUAL), o `RESTO`.
- ✦ **`Bucket_Valor_Ticket`** — Rangos del valor del ticket con IGV para evaluar umbrales de descuento (S/45–S/50).

### 8.5 Medidas agregadas estándar (nombres canónicos)

- ✦ **`Vta_con_IGV`** = `SUM(Vta_Igv_Prod)`
- ✦ **`Vta_sin_IGV`** = `SUM(Vta_SinIgv_Prod)`
- ✦ **`Margen_Bruto`** = `SUM(marg_bru_total_prod)`
- ✦ **`Costo`** = `SUM(cost_vent_total_prod)`
- ✦ **`Vta_Udds`** = `SUM(total_unid_vend_prod)`
- ✦ **`Vta_IGV_PBlanco`** = `SUM(vent_pre_list_prod)` (venta a precio lista)
- ✦ **`Margen_Bruto_PBlanco`** = `SUM(vent_pre_list_sinigv_prod - cost_vent_total_prod)`
- ✦ **`Num_Skus`** = `COUNT(DISTINCT Codigo_Producto)`
- ✦ **`Num_Tickets`** = `COUNT(DISTINCT Ticket_Key)` (o `Nro_Documento`)
- ✦ **`Num_Clientes`** = `COUNT(DISTINCT Codigo_Cliente)`
- ✦ **`Num_Tiendas`** = `COUNT(DISTINCT Codigo_Tienda)`

---

## 9. Tablas referenciadas pero NO documentadas (vacíos a cerrar)

Estas tablas/columnas se usan en las vistas o en `FACT_VENTAS` pero no tienen definición en el origen (`TABLAS.txt`). Prioridad alta para evitar errores.

- ✦ **`DIM_TIENDA`** — Usada en ambas vistas. Columnas detectadas: `Codigo_Tienda` (PK), `Nombre_Tienda`, `Anio_Apertura`. **Falta el DDL/SELECT completo.**
- ✦ **`Codigo_Empresa`** (en FACT_VENTAS) — No hay `DIM_EMPRESA` documentada.
- ✦ **`Codigo_Empleado`** (en FACT_VENTAS) — No hay `DIM_EMPLEADO` documentada.
- ✦ **`Id_Segmento` / `Codigo_Antiguedad` / `Id_tipdocventa`** — Sin catálogo/dimensión de referencia documentada.

---

## 10. Riesgos y notas para evitar errores

- ✦ **Acentos y `ñ` en identificadores:** siempre encerrar en corchetes `[Año]`, `[SemanaAño]`. Evita fallos de parseo.
- ✦ **Mojibake de encoding:** `NIÃ‘AS` = `NIÑAS`. Contemplar ambos en filtros (`IN (N'NIÑAS', N'NIÃ‘AS')`).
- ✦ **Case de columnas:** conviven mayúsculas y minúsculas (`identidad_valida_RFM`, `segmento_act_descrip`, `TEMPORADA`). SQL Server suele ser case-insensitive en nombres, pero respetar el original evita confusiones.
- ✦ **Doble nivel de promoción/descuento:** existe promo/descuento a nivel **línea** (`Codigo_Promocion`, `Dscto_Producto`) y a nivel **documento** (`Codigo_Promocion_Documento`, `Dscto_Documento`). No mezclarlos al agregar.
- ✦ **Versiones `_V2`:** `Tipo_Cliente`/`Tipo_Cliente_V2`, `Tipo_Documento`/`Tipo_Documento_V2`. Definir cuál es la oficial para reportes.
- ✦ **IGV:** venta con IGV siempre es la suma de base + IGV; nunca asumir que una sola columna ya lo incluye.
- ✦ **Tipos de dato inferidos:** confirmar todos contra el catálogo real antes de cerrar el glosario (ver §11).
- En la DIM_PRODUCTO o FACT_VENTAS, puede estar contaminados con las siguientes lineas, porfavor no considerarlas:      'GIFTCARDS','LICENCIAS','SUMINISTROS - DESPACHO','SUMINISTROS - CONSUMO','SUMINISTROS - ACONDICIONAMIENTO','SERVICIOS','TECNOLOGIA','ACTIVOS'.

---

## 11. Cómo confirmar tipos de dato reales (opcional)

Para reemplazar los tipos inferidos por los reales, ejecutar en SQL Server:

```sql
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    ORDINAL_POSITION,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    NUMERIC_PRECISION,
    NUMERIC_SCALE,
    IS_NULLABLE
FROM [SIFRAH_DWH].INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN (
    'DIM_PRODUCTO','DIM_PROMOCIONES','DIM_TIEMPO','DIM_CLIENTE',
    'DIM_TIPODOCUMENTO','DIM_TIENDA','FACT_VENTAS','FACT_KARDEX'
)
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

> Con ese resultado completo la columna "tipo inferido" pasa a ser tipo confirmado y el glosario queda 100% cerrado.

Por ejemplo, una consulta SQL (se debe llamar asi):

```sql
SELECT TOP (1000) [Codigo_Empresa]
      ,[Nombre_Empresa]
  FROM [SIFRAH_DWH].[dbo].[DIM_EMPRESA]
```

## 12. Otras dimensiones

### a. DIM_ANTIGUEDAD

Contiene los tipos de datos:
[Id_antiguedad] ,[Descr_antiguedad] ,[Dias_antiguedad],[De],[A],[Inv_Sano]
Permite estandarizar el tiempo de antiguedad.

Id_antiguedad	Descr_antiguedad	Dias_antiguedad	De	A	Inv_Sano
0	Sin Antigüedad	0	0	0	1
1	1 a 30 días	30	1	30	1
2	31 a 60 días	60	31	60	1
3	61 a 90 días	90	61	90	1
4	91 a 120 días	120	91	120	1
5	121 a 180 días	180	121	180	1
6	181 a 270 días	270	181	270	1
7	271 a 365 días	365	271	365	0
8	Mayor a 1 año	366	366	7300	0

### b. DIM_EMPRESA

Contiene los siguientes datos. Recordar que solo se necesita analizar los datos de Sifrah:

Codigo_Empresa	Nombre_Empresa
1	SIFRAH BIJOU S.A.C
2	AXTRACORP S.A.C
3	VILLA MBC LOGISTICA S.A.C
4	CHM COMPANY S.A.C
1000	NO MAPEADO

### c.

FILTROS

Respecto a la siguiente consulta

- WHERE p.[Nombre_Linea] NOT IN (
- 'GIFTCARDS','LICENCIAS','SUMINISTROS - DESPACHO','SUMINISTROS - CONSUMO',
- 'SUMINISTROS - ACONDICIONAMIENTO','SERVICIOS','TECNOLOGIA','ACTIVOS'
- )
- AND vp.[Codigo_Tienda] NOT IN (0,3,27,28,29,9996,9997,9998)

Se debe tener en cuenta en no usar las siguientes lineas para analisis de la DIM_PRODUCTO, debido a que son giftcards, bolsas de despacho, pagos de servicios, entre otros.

Estos datos no nos serviría. Al menos que se consulte ESPECIFICAMENTE por algunas de estas lineas.

Respecto a las tiendas en la DIM_TIENDA esas tiendas son almacenes. Por lo que no deben considerarse para analisis de venta ahi. Al menos que se considere  estrictamente necesario O SE PIDA AL USUARIO. Creo que para Kardex si es util, por lo que se debe considerar en criterio.
