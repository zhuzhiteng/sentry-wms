const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildOutboundConfirmation,
  buildOutboundScanBody,
  buildReceiptConfirmation,
  buildReceiptScanBody,
} = require('../utils/payload');

test('outbound scan only sends identity read from the label', () => {
  const body = buildOutboundScanBody(
    '1-1',
    'QR-1',
    {
      material_code: 'MAT-LABEL',
      item_name: '吊牌品名',
      batch_no: 'B-01',
      label_quantity: '2',
    },
  );

  assert.equal(body.tag_suffix, '1-1');
  assert.equal(body.material_code, 'MAT-LABEL');
  assert.equal(body.item_name, '吊牌品名');
  assert.equal(body.label_quantity, 2);
  assert.equal(body.ship_no, undefined);
});

test('receipt scan carries printed label fields without task fallbacks', () => {
  const body = buildReceiptScanBody(
    '2-1',
    'QR-2',
    {
      engineering_no: 'H1613',
      manufacturer_name: '船厂配件厂',
      installation_pallet_no: 'P-2',
      destination: 'A 区 / A1',
    },
  );

  assert.equal(body.tag_suffix, '2-1');
  assert.equal(body.engineering_no, 'H1613');
  assert.equal(body.manufacturer_name, '船厂配件厂');
  assert.equal(body.installation_pallet_no, 'P-2');
  assert.equal(body.label_quantity, undefined);
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
