import re
import unicodedata


def normalizar_nombre(nombre):
    texto = unicodedata.normalize("NFKD", nombre)
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).casefold().split())


def variantes_telefono(telefono):
    numero = re.sub(r"\D", "", telefono)
    if not numero:
        return []
    if len(numero) == 12 and numero.startswith("52"):
        return [numero, numero[2:]]
    if len(numero) == 10:
        return [numero, "52" + numero]
    return [numero]
