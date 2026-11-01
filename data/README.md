# Ficha del dataset: `claims_etiquetado.csv`

Dataset propio de **240 claims** en español creado en la Actividad 4 para ClaimCheck IA (organismo certificador
ficticio *CertiBajío, S.C.*). **No proviene de etiquetas reales de clientes.** Se reutiliza sin cambios
(SHA-256 `d596dd2428c87ecdf35fdfc57c72eadc921d934a76ce7286625012622d4e0186`, registrado en los metadatos del modelo).

| Clase | Total | dev (entrenamiento) | test (prueba) | Casos frontera |
|---|---|---|---|---|
| NUTRIMENTAL | 70 | 21 | 49 | 10 |
| SALUD | 60 | 18 | 42 | 18 |
| AUSENCIA | 55 | 16 | 39 | 8 |
| MARKETING | 55 | 16 | 39 | 7 |
| **Total** | **240** | **71** | **169** | **43** |

## Uso en la Fase 2

- `dev` (71 claims): entrenamiento, elección de C por validación cruzada y elección del umbral τ.
- `test` (169 claims): solo medición. Es el mismo conjunto con el que se evaluaron los modelos zero-shot de la
  Actividad 4, así que la comparación es directa.

## Campos

| Campo | Descripción |
|---|---|
| `id_claim` | Identificador (`CLM-0001` … `CLM-0240`) |
| `texto_claim` | Claim tal como aparecería en el empaque; entrada del modelo |
| `categoria` | Etiqueta objetivo: `NUTRIMENTAL`, `SALUD`, `AUSENCIA`, `MARKETING` |
| `subtipo` | Subtipo fino para el análisis de errores |
| `referencia_normativa` | Marco que inspira la redacción (contexto, no dictamen) |
| `dificultad` | `estandar` o `ambiguo` (caso frontera entre dos clases) |
| `origen_registro` | `redaccion_manual` (133) o `plantilla` (107) |
| `n_palabras` | Palabras del claim |
| `particion` | `dev` o `test` |

## Guía de etiquetado (en este orden)

1. **SALUD**: relaciona un alimento o nutrimento con la salud, una función del cuerpo o la reducción de un riesgo.
2. **NUTRIMENTAL**: presencia, cantidad, ausencia o comparación de un nutrimento.
3. **AUSENCIA**: ausencia de algo que no es nutrimento (alérgeno, aditivo, ingrediente, práctica).
4. **MARKETING**: calidad, origen, proceso, sabor o sostenibilidad, sin referencia a nutrimentos ni a la salud.

Marcos de referencia: Reg. (CE) 1924/2006, Reg. (UE) 432/2012, Reg. de Ejecución (UE) 828/2014,
Reg. (UE) 1169/2011, FDA 21 CFR 101 y NOM-051-SCFI/SSA1-2010.
