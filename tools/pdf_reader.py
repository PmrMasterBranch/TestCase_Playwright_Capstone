# tools/pdf_reader.py
# Reads PDF file and extracts raw text
# Used by Agent A before sending to LLM

import pdfplumber
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts full text from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Full text content of the PDF as string
        
    Raises:
        FileNotFoundError: If PDF file does not exist
        Exception: If PDF cannot be read
    """
    path = Path(pdf_path)
    
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    if not path.suffix.lower() == ".pdf":
        raise ValueError(f"File is not a PDF: {pdf_path}")
    
    full_text = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"PDF has {total_pages} pages")
            
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text:
                    full_text.append(f"--- Page {page_num} ---\n{text}")
                    logger.info(f"Extracted page {page_num}/{total_pages}")
                else:
                    logger.warning(f"Page {page_num} has no extractable text")
                    
    except Exception as e:
        logger.error(f"Error reading PDF: {e}")
        raise Exception(f"Failed to read PDF: {e}")
    
    if not full_text:
        raise Exception("PDF has no extractable text content")
    
    combined = "\n\n".join(full_text)
    logger.info(f"Total extracted text length: {len(combined)} characters")
    
    return combined


def get_pdf_metadata(pdf_path: str) -> dict:
    """
    Gets basic metadata about the PDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Dict with page_count, file_name, file_size
    """
    path = Path(pdf_path)
    
    with pdfplumber.open(pdf_path) as pdf:
        return {
            "file_name"  : path.name,
            "file_size"  : f"{path.stat().st_size / 1024:.1f} KB",
            "page_count" : len(pdf.pages),
        }
