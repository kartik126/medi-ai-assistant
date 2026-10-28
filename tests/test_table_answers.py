"""Table column association and presentation, using generated changing values."""
from pathlib import Path
import pymupdf
import pytest
from backend.pdf_service import extract_pdf
from backend.chunking import chunk_page
from backend.table_answers import project_page
from backend.presentation import clean_text, clean_answer


def table_pdf(vaf='23.4%', fold='4.2', gene='GENE8'):
    with pymupdf.open() as doc:
        for _ in range(3):
            doc.new_page().insert_text((50,50),'Synthetic test cover')
        page = doc.new_page()
        for x,t in [(50,'Gene'),(120,'Alteration'),(210,'Location'),(280,'VAF'),(370,'Transcript ID')]:
            page.insert_text((x,100),t,fontsize=10)
        for x,t in [(50,gene),(120,'c.273G>A'),(210,'exon 4'),(280,vaf),(370,'NM_000546.5')]:
            page.insert_text((x,120),t,fontsize=10)
        for x,t in [(50,'Gene'),(120,'Alteration'),(210,'Location'),(280,'Fold Change'),(390,'Transcript ID')]:
            page.insert_text((x,180),t,fontsize=10)
        page.insert_text((330,190),'for',fontsize=8)  # interleaved watermark
        for x,t in [(50,'GENE9'),(120,'gain'),(210,'chr17'),(290,fold),(390,'NM_004448.2')]:
            page.insert_text((x,200),t,fontsize=10)
        return doc.tobytes()


def sources_for(content):
    text = extract_pdf(content,'test.pdf',100)[3].text
    return [dict(text=c.text,document_id='a',filename='test.pdf',page_number=4) for c in chunk_page(text)]


@pytest.mark.parametrize('vaf,fold', [('23.4%','4.2'),('8.6%','9.3')])
def test_requested_column_is_data_driven_and_distinct_from_location(vaf,fold):
    content=table_pdf(vaf,fold)
    with pymupdf.open(stream=content,filetype='pdf') as doc:
        first=project_page('What is GENE8 variant allele frequency?',doc[3],sources_for(content))
        second=project_page('What is GENE9 gain fold change?',doc[3],sources_for(content))
    assert [f.display for f in first]==[f'GENE8 variant allele frequency: {vaf}.']
    assert [f.display for f in second]==[f'GENE9 gain fold change: {fold}.']
    assert all(f.source['page_number']==4 for f in first+second)
    assert 'c.273G>A' in first[0].text and 'NM_000546.5' in first[0].text
    assert first[0].display not in first[0].text


def test_subject_match_does_not_confuse_gene_with_fusion():
    content=table_pdf(gene='GENE8-GENE9')
    with pymupdf.open(stream=content,filetype='pdf') as doc:
        assert project_page('What is GENE8 VAF?',doc[3],sources_for(content))==[]


def test_missing_quotation_cannot_produce_a_formatted_fact():
    content=table_pdf()
    with pymupdf.open(stream=content,filetype='pdf') as doc:
        assert project_page('What is GENE8 VAF?',doc[3],[dict(text='unrelated')])==[]


def test_cleanup_preserves_scientific_text_and_only_decodes_formatting():
    scientific='TP53 NM_000546.5:c.273G>A p.W91* ERBB2-NTRK3 17.9% 7.1 µg/mL'
    assert clean_text(scientific)==scientific
    assert clean_text('\\nTP53\\t17.9%\\r\\nERBB2  7.1\x83')=='TP53 17.9% ERBB2 7.1'
    assert clean_text(r'c.123\456del')==r'c.123\456del'
    assert clean_answer('TP53 17.9%\n\nERBB2 7.1')=='TP53 17.9%\n\nERBB2 7.1'
