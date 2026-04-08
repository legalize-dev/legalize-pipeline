# ------------------------------------- #
#          Developed/Edited by:         #
#           Lampros KAFIDAS             #
# https://www.linkedin.com/in/kafidas/  #
#      https://github.com/kafidas       #
# ------------------------------------- #

###### Python code for extracting readable text from pdf files of et.gr (edition 2024)
###### Tested for Issues A' that contain formal laws (some ending lines may be omitted)

import os
import fitz  # PyMuPDF
import re
import time


def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    clipped_text = []  # Use a list to store clipped text for each page

    # Set to store potential header/footer text
    header_text = set()

    def merge_lines_if_hyphen(lines):
        merged_lines = []
        i = 0
        while i < len(lines):
            current_line = lines[i].strip()

            # Check if the current line ends with a hyphen and the character before the hyphen is not a space
            while current_line.endswith("-") and (
                len(current_line) > 1 and current_line[-2] != " "
            ):
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                current_line = (
                    current_line[:-1] + next_line
                )  # Merge current line with the next line
                i += 1  # Skip the next line since it was merged

            merged_lines.append(current_line)  # Add the merged or current line
            i += 1  # Move to the next line

        return merged_lines

    def remove_blank_lines(text):
        return "\n".join(line for line in text.splitlines() if line.strip())

    # Collect the first 3 lines of each page as potential headers (skip for the first page)
    for page_num in range(1, doc.page_count):  # Start from the second page to the last page
        page = doc.load_page(page_num)
        page_text = page.get_text("text").split("\n")

        # Add the first 3 lines as headers to the set
        for line in page_text[:3]:  # The first 3 lines
            header_text.add(line.strip())

    # Now extract the text excluding the detected header lines
    for page_num in range(doc.page_count - 1):
        page = doc.load_page(page_num)
        page_text = re.split(r"\n|\r\n|\r|\u2028|\u2029", page.get_text("text"))
        page_width = page.rect.width
        page_height = page.rect.height
        if round(page_width) != 595 and round(page_height) != 842:
            print(
                f"Not standard A4 page found in pdf file: Page {page_num + 1}: Width = {page_width}, Height = {page_height}"
            )

        if page_num == 0:  # For the first page, omit lines
            exclusion_count = 0
            inside_range = False
            filtered_text = []
            clipped_page_text = []

            for line in page_text:
                if "ΕΦΗΜΕΡΙΔΑ" in line or "ΕΦΗΜΕΡΙ∆Α" in line or "Digitally" in line:
                    inside_range = True
                if (
                    "Verified" in line
                    or exclusion_count == 11
                    or "NOMOΣ" in line
                    or "ΝΟΜΟΣ" in line
                ):
                    inside_range = False

                if not inside_range:
                    filtered_text.append(line)
                else:
                    clipped_page_text.append(line)  # Add to clipped if within excluded range
                exclusion_count += 1

            clipped_text.append("\n".join(clipped_page_text))  # Capture the clipped lines
            filtered_text = "\n".join(filtered_text)
        else:
            # Exclude lines that are in the header set for other pages
            filtered_text = "\n".join(line for line in page_text if line.strip() not in header_text)
            clipped_page_text = "\n".join(line for line in page_text if line.strip() in header_text)
            clipped_text.append(clipped_page_text)

        # Merge lines that end with a hyphen and are not followed by a space
        lines = filtered_text.split("\n")
        merged_lines = merge_lines_if_hyphen(lines)
        filtered_text = "\n".join(merged_lines)

        # Remove lines starting with "Verified"
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("Verified"):
                clipped_text.append("".join(stripped_line))
        filtered_text = "\n".join(
            line for line in filtered_text.split("\n") if not line.strip().startswith("Verified")
        )

        filtered_text = re.sub(r"  ", " ", filtered_text)  # Collapsing multiple spaces into one

        text += "\n" + filtered_text

    # Handle last page separately
    last_page_text = ""
    if doc.page_count > 1:
        last_page = doc.load_page(doc.page_count - 1)
        last_page_text = last_page.get_text("text")
        final_text = ""
        # Check the 4th line in last_page_text (omits 3-line header)
        last_page_lines = last_page_text.splitlines()
        if len(last_page_lines) >= 4:
            fourth_line = last_page_lines[3].strip()
            # Check if the 4th line does not start with last page closing arguments
            if not (
                (fourth_line.startswith("*") and fourth_line.endswith("*"))
                or (fourth_line.startswith("Ταχυδρομική"))
            ):
                # Include the contents of that line until the end of the last page -4 lines
                print(f"Adding last page contents {fourth_line}")
                final_text += "\n" + "\n".join(last_page_lines[3:-4])
                clipped_text.append("\n".join(last_page_lines[0:3]))
                clipped_text.append("\n".join(last_page_lines[-4:]))
            text += final_text

    text = remove_blank_lines(text)

    return text, "\n".join(clipped_text), last_page_text


def process_pdfs_in_folder(input_folder, output_folder):
    # Ensure the output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Get all PDF files from the input folder
    pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".pdf")]

    # Process each PDF file
    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_folder, pdf_file)
        extracted_text, clipped_text, last_page_text = extract_text_from_pdf(pdf_path)

        # Define output text file path for the main text
        output_txt_file = os.path.join(output_folder, f"{os.path.splitext(pdf_file)[0]}.txt")
        with open(output_txt_file, "w", encoding="utf-8") as text_file:
            text_file.write(extracted_text)

        # Define output text file path for the clipped text
        output_clipped_txt_file = os.path.join(
            output_folder, f"{os.path.splitext(pdf_file)[0]}_trims.txt"
        )
        with open(output_clipped_txt_file, "w", encoding="utf-8") as clipped_file:
            clipped_file.write(clipped_text)

        # Define output text file path for the last page
        output_last_page_txt_file = os.path.join(
            output_folder, f"{os.path.splitext(pdf_file)[0]}_last_page.txt"
        )
        with open(output_last_page_txt_file, "w", encoding="utf-8") as last_page_file:
            last_page_file.write(last_page_text)

        print(f"Extracted text from {pdf_file} and saved to {output_txt_file}")
        print(f"Clipped text from {pdf_file} saved to {output_clipped_txt_file}")
        print(f"Last page text from {pdf_file} saved to {output_last_page_txt_file}")

        # Add a pause before processing the next PDF
        print("A small pause...\n")
        time.sleep(0.1)


# Define the input and output folders
input_folder = "pdf_files"
output_folder = "pdf_files/extracted_text_files"

# Process the PDFs
process_pdfs_in_folder(input_folder, output_folder)
