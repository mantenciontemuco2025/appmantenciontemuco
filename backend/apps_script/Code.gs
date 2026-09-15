/** Maintenance Platform — real signature images for Google Sheets. */
const SIGNATURE_MARKER = 'maintenance-platform-signature:';
const SIGNATURE_ANCHORS = {
  requested_by: { column: 2, row: 31 }, // B31
  approved_by: { column: 5, row: 31 }, // E31 (legacy wire name)
  performed_by: { column: 5, row: 31 }, // E31
};

// Health check for confirming that the /exec deployment points to this code.
function doGet() {
  return json_({ ok: true, service: 'signature-webhook' });
}

function doPost(event) {
  try {
    const payload = JSON.parse(event.postData && event.postData.contents || '{}');
    const expectedSecret = PropertiesService.getScriptProperties()
      .getProperty('SIGNATURE_WEBHOOK_SECRET');
    if (!expectedSecret || payload.secret !== expectedSecret) {
      throw new Error('Solicitud de firma no autorizada.');
    }
    const hasInlineSignature = typeof payload.signatureData === 'string' &&
      payload.signatureData.length > 0;
    const hasDriveSignature = /^[a-zA-Z0-9_-]+$/.test(payload.signatureFileId || '');
    if (!/^[a-zA-Z0-9_-]+$/.test(payload.spreadsheetId || '') ||
        (!hasInlineSignature && !hasDriveSignature) ||
        !SIGNATURE_ANCHORS[payload.field] ||
        typeof payload.sheetName !== 'string') {
      throw new Error('Solicitud de firma inválida.');
    }
    if (hasInlineSignature && payload.signatureData.length > 2500000) {
      throw new Error('La firma optimizada es demasiado grande.');
    }
    if (hasInlineSignature &&
        ['image/jpeg', 'image/png'].indexOf(payload.signatureMimeType) === -1) {
      throw new Error('Formato de firma optimizada no admitido.');
    }

    const spreadsheet = SpreadsheetApp.openById(payload.spreadsheetId);
    const sheet = spreadsheet.getSheetByName(payload.sheetName);
    if (!sheet) throw new Error('No se encontró la pestaña destino de la OT.');

    const marker = SIGNATURE_MARKER + payload.field;
    sheet.getImages().forEach((image) => {
      if (image.getAltTextTitle() === marker) image.remove();
    });

    const blob = hasInlineSignature
      ? Utilities.newBlob(
          Utilities.base64Decode(payload.signatureData),
          payload.signatureMimeType,
          'signature.jpg')
      : DriveApp.getFileById(payload.signatureFileId).getBlob();
    const anchor = SIGNATURE_ANCHORS[payload.field];
    const image = sheet.insertImage(blob, anchor.column, anchor.row, 0, 0);
    image.setWidth(200).setHeight(80).setAltTextTitle(marker);
    return json_({ ok: true });
  } catch (error) {
    return json_({ ok: false, error: error.message || String(error) });
  }
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
