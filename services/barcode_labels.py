"""EAN-13 label encoding without external dependencies."""


def ean13_check_digit(body):
    if len(body) != 12 or any(c not in "0123456789" for c in body):
        raise ValueError("EAN-13 uchun 12 ta raqam kerak")
    total = sum(
        int(c) * (1 if i % 2 == 0 else 3)
        for i, c in enumerate(body)
    )
    return str((-total) % 10)


def ean13_bits(code):
    code = str(code)
    if (
        len(code) != 13
        or any(c not in "0123456789" for c in code)
        or ean13_check_digit(code[:12]) != code[-1]
    ):
        raise ValueError(
            "Bu kod EAN-13 formatida emas. "
            "Ushbu chop etish funksiyasi 13 xonali EAN-13 kodlar uchun."
        )

    left = (
        "0001101", "0011001", "0010011", "0111101", "0100011",
        "0110001", "0101111", "0111011", "0110111", "0001011",
    )
    right = tuple(
        "".join("1" if bit == "0" else "0" for bit in pattern)
        for pattern in left
    )
    even = tuple(pattern[::-1] for pattern in right)
    parity = (
        "LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
        "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL",
    )
    result = "101"
    for digit, kind in zip(code[1:7], parity[int(code[0])]):
        result += (left if kind == "L" else even)[int(digit)]
    result += "01010"
    result += "".join(right[int(digit)] for digit in code[7:])
    return result + "101"
