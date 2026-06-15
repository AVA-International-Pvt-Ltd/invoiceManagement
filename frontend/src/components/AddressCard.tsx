type Address = {
  name?: string
  address?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
  gstin?: string
  state_code?: string
  pan?: string
  place_of_supply?: string
}

type Props = {
  title: string
  data?: Address
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <p>
      <strong>{label}:</strong> {value}
    </p>
  )
}

export function AddressCard({ title, data }: Props) {
  if (!data) return null
  return (
    <div className="address-card">
      <h3>{title}</h3>
      <Field label="Name" value={data.name} />
      <Field label="Address" value={data.address} />
      <Field label="City" value={data.city} />
      <Field label="State" value={data.state} />
      <Field label="Postal Code" value={data.postal_code} />
      <Field label="Country" value={data.country} />
      <Field label="GSTIN" value={data.gstin} />
      <Field label="State Code" value={data.state_code} />
      <Field label="PAN" value={data.pan} />
      <Field label="Place of Supply" value={data.place_of_supply} />
    </div>
  )
}
