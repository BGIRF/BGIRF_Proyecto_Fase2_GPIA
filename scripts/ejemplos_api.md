# Ejemplos de consumo de la API

Sustituye `http://localhost:8000` por la URL pública (por ejemplo, `https://claimcheck-api.onrender.com`) para
probar el servicio desplegado en la nube.

## PowerShell (Windows)

```powershell
$api = "http://localhost:8000"

# Salud y metadatos del modelo
Invoke-RestMethod "$api/health"
Invoke-RestMethod "$api/api/v1/info" | Select-Object nombre, version_modelo, umbral_confianza

# Un claim
Invoke-RestMethod -Method Post -Uri "$api/api/v1/clasificar" `
  -ContentType "application/json; charset=utf-8" -Body '{"texto": "Fuente de fibra"}'

# Lote
$lote = @{ claims = @("Sin gluten", "Receta tradicional", "Bajo en sodio") } | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri "$api/api/v1/clasificar/lote" `
  -ContentType "application/json; charset=utf-8" -Body $lote).resultados | Format-Table texto, categoria, confianza

# Etiqueta completa con tabla nutrimental
$etiqueta = @{
  producto = "Cereal integral de avena"
  claims = @("Fuente de fibra", "Bajo en grasa", "Sin azúcares añadidos", "Sin gluten")
  datos_nutrimentales = @{ estado_fisico = "solido"; energia_kcal = 372; grasa_g = 6.5
                           azucares_g = 1.2; sodio_mg = 8; fibra_g = 9.8; proteina_g = 13.1 }
} | ConvertTo-Json -Depth 3
$r = Invoke-RestMethod -Method Post -Uri "$api/api/v1/analizar-etiqueta" `
  -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($etiqueta))
$r.resultados | Format-Table texto, categoria, requiere_confirmacion, @{n="regla"; e={$_.regla.veredicto_propuesto}}

# Caso extremo: texto vacío → la API responde 422
try { Invoke-RestMethod -Method Post -Uri "$api/api/v1/clasificar" -ContentType "application/json" -Body '{"texto": ""}' }
catch { $_.Exception.Response.StatusCode.value__ }
```

## curl (macOS, Linux, Git Bash)

```bash
API=http://localhost:8000
curl $API/health
curl -X POST $API/api/v1/clasificar -H "Content-Type: application/json" -d '{"texto": "Fuente de fibra"}'
curl -X POST $API/api/v1/clasificar/lote -H "Content-Type: application/json" \
  -d '{"claims": ["Sin gluten", "Receta tradicional", "Bajo en sodio"]}'
curl -X POST $API/api/v1/analizar-etiqueta -H "Content-Type: application/json" -d '{
  "producto": "Bebida de avena",
  "claims": ["Bajo en azúcares", "Bajo valor energético", "Fuente de proteínas"],
  "datos_nutrimentales": {"estado_fisico": "liquido", "energia_kcal": 18, "azucares_g": 2.0, "proteina_g": 0.5}
}'
# Caso extremo: lote de 51 claims → 422
python3 -c 'import json; print(json.dumps({"claims": ["Sin gluten"]*51}))' | \
  curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/api/v1/clasificar/lote -H "Content-Type: application/json" -d @-
```

## Python

```python
import json, urllib.request

def post(ruta, cuerpo, api="http://localhost:8000"):
    req = urllib.request.Request(api + ruta, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

print(post("/api/v1/clasificar", {"texto": "El calcio ayuda a mantener los huesos"})["categoria"])
```
