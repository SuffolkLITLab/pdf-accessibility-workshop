import io
import pikepdf
from workshop.pdf_accessibility import inspect_pdf_accessibility
from web.app import app


def test_plain_pdf_has_no_form_failures(tmp_path):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page()
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pdf.make_indirect(
        pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                          BaseFont=pikepdf.Name.Helvetica))))
    page.Contents = pdf.make_stream(b'BT /F1 20 Tf 72 700 Td (Community meeting) Tj 0 -40 Td /F1 12 Tf (Everyone is welcome.) Tj ET')
    path = tmp_path / 'plain.pdf'
    pdf.save(path)
    data = inspect_pdf_accessibility(str(path))
    assert data['fields'] == []
    # Exercise the HTTP response as well as the engine contract.
    response = app.test_client().post('/pdf-labeler/api/accessibility-inspect',
        data={'file': (io.BytesIO(path.read_bytes()), 'plain.pdf')})
    assert response.status_code == 200
    report = next(value for value in response.json['data'].values()
                  if isinstance(value, dict) and 'issues' in value and 'summary' in value)
    issues = {item['id']: item for item in report['issues']}
    for key in ['field-names', 'form-structure-alt', 'form-structure-objects', 'tab-order']:
        assert issues[key]['status'] == 'not_applicable'
        assert issues[key]['count'] == 0
    assert report['summary']['failed_checks'] == sum(
        item['status'] in {'fail', 'review'} for item in report['issues'])


def test_review_routes_do_not_require_server_state():
    client = app.test_client()
    assert client.get('/review/11223344-5566-7788-9900-aabbccddeeff').status_code == 200
    assert client.get('/review/not-a-review-id').status_code == 404


def test_ai_review_does_not_treat_missing_controls_as_a_defect():
    from unittest.mock import patch
    from workshop.pdf_accessibility import review_pdf_accessibility_with_ai
    with patch("workshop.workshop_ai.chat_completion", return_value={"findings": []}) as complete:
        review_pdf_accessibility_with_ai({"fields": []})
    instructions = complete.call_args.kwargs["messages"][0]["content"]
    assert "Interactive form fields are optional" in instructions
    assert "never report zero fields as a defect" in instructions
