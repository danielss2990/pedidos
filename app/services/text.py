import re
import unicodedata
from decimal import Decimal


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e com espaços simples — usado na busca do catálogo."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    no_accents = no_accents.replace("²", "2").replace("³", "3")
    return re.sub(r"\s+", " ", no_accents.lower()).strip()


def brl(value: Decimal) -> str:
    """Formata um valor em reais: Decimal('1234.5') -> 'R$ 1.234,50'."""
    inteiro, centavos = f"{value:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def qty(value: Decimal) -> str:
    """Quantidade sem zeros à direita e com vírgula decimal: 2.500 -> '2,5'."""
    text = f"{value.normalize():f}"
    return text.replace(".", ",")
