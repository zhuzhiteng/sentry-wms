const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildOutboundConfirmation,
  buildReceiptConfirmation,
  buildScanBody,
} = require('../utils/payload');

test('builds a scan body with server-authoritative ticket identity', () => {
  const body = buildScanBody(
    {
      ship_no: 'H1613',
      engineering_no: 'H1613',
      production_drawing_no: 'D-1',
      material_code: 'MAT-1',
      item_name: '船用支架',
      planned_quantity: '4.000',
    },
    '1-1',
    'QR-1',
    { batch_no: 'B-01' },
  );

  assert.equal(body.tag_suffix, '1-1');
  assert.equal(body.material_code, 'MAT-1');
  assert.equal(body.label_quantity, 4);
});

test('outbound confirmation requires every local evidence item', () => {
  const body = buildOutboundConfirmation(
    'outbound-1',
    [
      {
        scan: { tag_suffix: '1-1', qr_payload: 'QR-1' },
        photo: { photo_id: 'photo-1' },
      },
      {
        scan: { tag_suffix: '1-2', qr_payload: 'QR-2' },
        photo: { photo_id: 'photo-2' },
      },
    ],
    'WX-1',
  );

  assert.equal(body.pallets.length, 2);
  assert.deepEqual(
    body.pallets.map((item) => item.photo_id),
    ['photo-1', 'photo-2'],
  );
});

test('receipt confirmation carries shortage reason without changing quantity', () => {
  const body = buildReceiptConfirmation({
    idempotencyKey: 'receipt-1',
    quantity: 3,
    evidence: [
      {
        scan: { tag_suffix: '1-1', qr_payload: 'QR-1' },
        photo: { photo_id: 'photo-1' },
      },
    ],
    differenceReason: '少 1 件',
    deviceId: 'WX-1',
  });

  assert.equal(body.received_quantity, 3);
  assert.equal(body.difference_reason, '少 1 件');
});
