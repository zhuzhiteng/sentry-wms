function parsedQuantity(value) {
  if (value === null || value === undefined || value === '') return undefined;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : undefined;
}

function omitEmpty(body) {
  return Object.fromEntries(
    Object.entries(body).filter(([, value]) => (
      value !== undefined && value !== null && value !== ''
    )),
  );
}

function buildReceiptScanBody(suffix, qrPayload, parsed) {
  return omitEmpty({
    tag_suffix: suffix,
    qr_payload: qrPayload,
    ship_no: parsed.ship_no,
    engineering_no: parsed.engineering_no,
    production_drawing_no: parsed.production_drawing_no,
    qr_pallet_no: parsed.qr_pallet_no,
    batch_no: parsed.batch_no || undefined,
    manufacturer_name: parsed.manufacturer_name,
    installation_pallet_no: parsed.installation_pallet_no,
    installation_pallet_name: parsed.installation_pallet_name,
    destination: parsed.destination,
    label_quantity: parsedQuantity(parsed.label_quantity),
  });
}

function buildOutboundScanBody(suffix, qrPayload, parsed) {
  return omitEmpty({
    tag_suffix: suffix,
    qr_payload: qrPayload,
    ship_no: parsed.ship_no,
    engineering_no: parsed.engineering_no,
    production_drawing_no: parsed.production_drawing_no,
    material_code: parsed.material_code,
    item_name: parsed.item_name,
    batch_no: parsed.batch_no,
    label_quantity: parsedQuantity(parsed.label_quantity),
  });
}

function buildOutboundConfirmation(idempotencyKey, evidence, deviceId) {
  return {
    idempotency_key: idempotencyKey,
    client_device_id: deviceId,
    pallets: evidence.map((item) => ({
      ...item.scan,
      photo_id: item.photo.photo_id,
    })),
  };
}

function buildReceiptConfirmation({
  idempotencyKey,
  quantity,
  evidence,
  differenceReason,
  deviceId,
}) {
  const body = {
    idempotency_key: idempotencyKey,
    received_quantity: Number(quantity),
    client_device_id: deviceId,
    pallets: evidence.map((item) => ({
      ...item.scan,
      photo_id: item.photo.photo_id,
    })),
  };
  if (differenceReason) body.difference_reason = differenceReason;
  return body;
}

module.exports = {
  buildOutboundConfirmation,
  buildOutboundScanBody,
  buildReceiptConfirmation,
  buildReceiptScanBody,
};
