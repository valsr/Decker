"""Common functionality."""


def column_print(
    header: str | list[str],
    rows: list[str] | list[list[str]],
    separator: str = "\t",
    include_header: bool = True,
    include_separator: bool = True,
    column_spacing: int = 4,
):
    """Prints a column of data with a header.

    Args:
        header (str): The header for the column.
        data (list[str]): The data to print in the column.
    """

    header_data = header.split(separator) if isinstance(header, str) else header

    row_data: list[list[str]] = []
    for row in rows:
        if isinstance(row, str):
            row_data.append(row.split(separator))
        else:
            if not isinstance(row, list):
                raise ValueError("Rows must be a list of strings or a list of lists of strings.")
            row_data.append(row)

    # Calculate column widths
    col_widths = []
    for i, column in enumerate(header_data):
        col_width = len(column) if include_header else 0
        for row in row_data:
            if i < len(row):
                col_width = max(col_width, len(str(row[i])))
        col_widths.append(col_width + column_spacing)

    if include_header:
        header_line = ""
        for i, column in enumerate(header_data):
            header_line += f"{column:{col_widths[i]}}"
        print(header_line)

        if include_separator:
            print("-" * len(header_line))

    # Print row data
    for row in row_data:
        line = ""
        for i, column in enumerate(row):
            line += f"{str(column):{col_widths[i]}}"
        print(line)
