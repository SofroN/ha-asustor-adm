"""Brand-ассеты интеграции: знак ASUSTOR в фирменном синем и wordmark.

Читаем PNG стандартной библиотекой: быстрый набор не требует Pillow, а
проверить нужно именно пиксели — размеры, фирменный цвет знака, прозрачный
фон и контраст светлого и тёмного вариантов логотипа.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BRAND = Path(__file__).parents[2] / "custom_components" / "asustor_adm" / "brand"

#: Заливка знака из исходного SVG (`dashboard-icons/svg/asustor.svg`).
BRAND_FILL = (0, 82, 164)  # #0052a4

#: Квадратные иконки: сторона в пикселях. Тёмного варианта нет: знак несёт
#: собственный фон, а Home Assistant берёт `icon.png` вместо отсутствующего
#: `dark_icon.png`.
ICONS = {
    "icon.png": 256,
    "icon@2x.png": 512,
}

#: Горизонтальные логотипы: ширина в пикселях.
LOGOS = {
    "logo.png": 300,
    "logo@2x.png": 600,
    "dark_logo.png": 300,
    "dark_logo@2x.png": 600,
}

_CHANNELS = 4


def _read_png(path: Path) -> tuple[int, int, int, list[bytes]]:
    """Разобрать PNG: ширину, высоту, тип цвета и строки RGBA."""
    data = path.read_bytes()
    width = height = depth = color_type = None
    idat = b""
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if chunk == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", body[:10])
        elif chunk == b"IDAT":
            idat += body
        pos += 12 + length
    assert width is not None and height is not None, path
    assert depth == 8, f"{path.name}: ожидается 8 бит на канал, получено {depth}"
    assert color_type == 6, f"{path.name}: ожидается RGBA, получено {color_type}"
    raw = zlib.decompress(idat)
    stride = width * _CHANNELS
    rows: list[bytes] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        _unfilter(filter_type, line, previous)
        rows.append(bytes(line))
        previous = line
    return width, height, color_type, rows


def _unfilter(filter_type: int, line: bytearray, previous: bytearray) -> None:
    """Восстановить строку сканирования по типу фильтра PNG."""
    stride = len(line)
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(_CHANNELS, stride):
            line[index] = (line[index] + line[index - _CHANNELS]) & 0xFF
        return
    if filter_type == 2:
        for index in range(stride):
            line[index] = (line[index] + previous[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(stride):
            left = line[index - _CHANNELS] if index >= _CHANNELS else 0
            line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        return
    if filter_type == 4:
        for index in range(stride):
            left = line[index - _CHANNELS] if index >= _CHANNELS else 0
            upper = previous[index]
            upper_left = previous[index - _CHANNELS] if index >= _CHANNELS else 0
            pa = abs(upper - upper_left)
            pb = abs(left - upper_left)
            pc = abs(left + upper - 2 * upper_left)
            if pa <= pb and pa <= pc:
                predictor = left
            elif pb <= pc:
                predictor = upper
            else:
                predictor = upper_left
            line[index] = (line[index] + predictor) & 0xFF
        return
    raise AssertionError(f"неизвестный тип фильтра PNG: {filter_type}")


def _pixels(rows: list[bytes]):
    """Перебрать пиксели в порядке строк: (x, y, r, g, b, alpha)."""
    for y, row in enumerate(rows):
        for x in range(len(row) // _CHANNELS):
            base = x * _CHANNELS
            yield x, y, row[base], row[base + 1], row[base + 2], row[base + 3]


def _bbox(rows: list[bytes]) -> tuple[int, int, int, int]:
    """Границы непрозрачных пикселей: left, top, right, bottom."""
    xs = [x for x, _, _, _, _, alpha in _pixels(rows) if alpha > 8]
    ys = [y for _, y, _, _, _, alpha in _pixels(rows) if alpha > 8]
    assert xs, "изображение полностью прозрачное"
    return min(xs), min(ys), max(xs), max(ys)


def _mean_luma(rows: list[bytes]) -> float:
    """Средняя яркость непрозрачных пикселей."""
    values = [
        0.299 * r + 0.587 * g + 0.114 * b
        for _, _, r, g, b, alpha in _pixels(rows)
        if alpha > 200
    ]
    assert values, "нет непрозрачных пикселей"
    return sum(values) / len(values)


def test_brand_assets_have_expected_sizes() -> None:
    """Иконки квадратные, логотипы вдвое крупнее в 2x, все файлы — RGBA."""
    for name, side in ICONS.items():
        width, height, _, _ = _read_png(BRAND / name)
        assert (width, height) == (side, side), name
    for name, width_expected in LOGOS.items():
        width, height, _, _ = _read_png(BRAND / name)
        assert width == width_expected, name
        assert height < width, name
    for single_name, double_name in (
        ("logo.png", "logo@2x.png"),
        ("dark_logo.png", "dark_logo@2x.png"),
    ):
        single = _read_png(BRAND / single_name)
        double = _read_png(BRAND / double_name)
        assert double[:2] == (single[0] * 2, single[1] * 2), single_name


def test_brand_icons_have_transparent_background() -> None:
    """Круг знака лежит на прозрачном квадрате, углы прозрачны."""
    for name in ICONS:
        width, height, _, rows = _read_png(BRAND / name)
        corners = (
            rows[0][3],
            rows[0][-1],
            rows[-1][3],
            rows[-1][-1],
        )
        assert set(corners) == {0}, f"{name}: углы не прозрачны"
        opaque = sum(1 for *_, alpha in _pixels(rows) if alpha > 8)
        share = opaque / (width * height)
        assert 0.6 < share < 0.9, f"{name}: непрозрачных пикселей {share:.1%}"


def test_brand_icons_use_brand_badge() -> None:
    """Знак залит фирменным синим, буквы wordmark белые."""
    for name in ICONS:
        _, _, _, rows = _read_png(BRAND / name)
        opaque = [px for px in _pixels(rows) if px[5] > 200]
        assert opaque, name
        blue = sum(
            1
            for _, _, r, g, b, _ in opaque
            if abs(r - BRAND_FILL[0]) < 12
            and abs(g - BRAND_FILL[1]) < 12
            and abs(b - BRAND_FILL[2]) < 12
        )
        white = sum(1 for _, _, r, g, b, _ in opaque if r > 240 and g > 240 and b > 240)
        assert blue / len(opaque) > 0.85, (
            f"{name}: фирменный синий {blue / len(opaque):.1%}"
        )
        assert 0.02 < white / len(opaque) < 0.10, (
            f"{name}: белые буквы {white / len(opaque):.1%}"
        )


def test_brand_icons_are_centered() -> None:
    """Знак стоит по центру квадрата: поля симметричны."""
    for name in ICONS:
        width, height, _, rows = _read_png(BRAND / name)
        left, top, right, bottom = _bbox(rows)
        assert abs(left - (width - 1 - right)) <= 2, name
        assert abs(top - (height - 1 - bottom)) <= 2, name


def test_brand_contrast_matches_theme() -> None:
    """Светлая тема получает тёмный логотип, тёмная — светлый."""
    dark = _mean_luma(_read_png(BRAND / "logo@2x.png")[3])
    light = _mean_luma(_read_png(BRAND / "dark_logo@2x.png")[3])
    assert dark < 40, f"logo@2x.png: средняя яркость {dark:.0f}"
    assert light > 215, f"dark_logo@2x.png: средняя яркость {light:.0f}"
