import docx
import PyPDF2

def extract_pdf(pdf_path):
    text = []
    with open(pdf_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text.append(t)
    return '\n'.join(text)

def extract_docx(docx_path):
    doc = docx.Document(docx_path)
    return '\n'.join([p.text for p in doc.paragraphs])

try:
    pdf_text = extract_pdf('DRL_Movie_Recommender.pdf')
    with open('extracted_pdf.txt', 'w', encoding='utf-8') as f:
        f.write(pdf_text)
    
    docx_text = extract_docx('total_NEW.docx')
    with open('extracted_docx.txt', 'w', encoding='utf-8') as f:
        f.write(docx_text)
    print("Extraction successful.")
except Exception as e:
    print(f"Error: {e}")
