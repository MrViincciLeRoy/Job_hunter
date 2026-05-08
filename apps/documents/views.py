from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from apps.documents.models import Document, DocumentType


def documents_list(request):
    docs = Document.objects.all()
    grouped = {}
    for choice_value, choice_label in DocumentType.choices:
        grouped[choice_value] = {
            "label": choice_label,
            "docs":  [d for d in docs if d.doc_type == choice_value],
        }
    return render(request, "documents/list.html", {
        "grouped":       grouped,
        "doc_type_choices": DocumentType.choices,
        "total":         docs.count(),
    })


@require_POST
def upload_document(request):
    doc_type = request.POST.get("doc_type")
    label    = request.POST.get("label", "").strip()
    note     = request.POST.get("note", "").strip()
    file     = request.FILES.get("file")

    if not doc_type or not file:
        messages.error(request, "Document type and file are required.")
        return redirect("documents_list")

    if doc_type not in dict(DocumentType.choices):
        messages.error(request, "Invalid document type.")
        return redirect("documents_list")

    # Deactivate previous version of same type
    Document.objects.filter(doc_type=doc_type, active=True).update(active=False)

    Document.objects.create(
        doc_type = doc_type,
        label    = label,
        file     = file,
        note     = note,
        active   = True,
    )
    messages.success(request, f"Uploaded {dict(DocumentType.choices)[doc_type]}.")
    return redirect("documents_list")


@require_POST
def delete_document(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    doc.file.delete(save=False)
    doc.delete()
    return JsonResponse({"deleted": True})


@require_POST
def set_active(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    Document.objects.filter(doc_type=doc.doc_type, active=True).update(active=False)
    doc.active = True
    doc.save(update_fields=["active"])
    return JsonResponse({"active": True})


def download_document(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.filename)