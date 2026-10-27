function buildScanBody(task, suffix, qrPayload, parsed) {
  return {
    tag_suffix: suffix,
    qr_payload: qrPayload,
    ship_no: task.ship_no,
    engineering_no: task.engineering_no,
    production_drawing_no: task.production_drawing_no,
    material_code: task.material_code,
    item_name: task.item_name,
    batch_no: parsed.batch_no || undefined,
    label_quantity: parsed.label_quantity
      ? Number(parsed.label_quantity)
      : Number(task.planned_quantity || task.declared_quantity),
  };
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
  buildReceiptConfirmation,
  buildScanBody,
};
