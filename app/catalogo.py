"""Catálogo de categorías: a qué checklist de revisión se enruta cada claim."""

CATEGORIAS = {
    "NUTRIMENTAL": {
        "descripcion": "Cantidad, presencia, ausencia o comparación de un nutrimento",
        "checklist": "CL-NUT · Umbrales contra la tabla nutrimental",
        "referencia_normativa": "Reg. (CE) 1924/2006, Arts. 8-9 y Anexo; FDA 21 CFR 101.13; NOM-051-SCFI/SSA1-2010",
    },
    "SALUD": {
        "descripcion": "Relación entre un nutrimento o alimento y la salud",
        "checklist": "CL-SAL · Declaraciones autorizadas y evidencia",
        "referencia_normativa": "Reg. (CE) 1924/2006, Arts. 10, 13 y 14; Reg. (UE) 432/2012; FDA 21 CFR 101.14",
    },
    "AUSENCIA": {
        "descripcion": "Ausencia de un alérgeno, aditivo o ingrediente que no es nutrimento",
        "checklist": "CL-AUS · Evidencia analítica y control de alérgenos",
        "referencia_normativa": "Reg. (UE) 1169/2011, Arts. 7 y 36; Reg. de Ejecución (UE) 828/2014; FDA 21 CFR 101.91",
    },
    "MARKETING": {
        "descripcion": "Calidad, origen, proceso, sabor o sostenibilidad",
        "checklist": "CL-MKT · Veracidad, que no induzca a error",
        "referencia_normativa": "Reg. (UE) 1169/2011, Art. 7; NOM-051-SCFI/SSA1-2010",
    },
}

AVISO_REVISOR = (
    "La IA propone, el revisor decide: este resultado es una preclasificación. "
    "La decisión de certificación la toma personal competente (ISO/IEC 17065)."
)
