from pydantic import BaseModel
from typing import Optional, List


class PostOffice(BaseModel):
    name: str
    branch_type: Optional[str]
    delivery_status: Optional[str]
    circle: Optional[str]
    district: str
    division: Optional[str]
    region: Optional[str]
    state: str
    country: str
    pincode: str


class PincodeResult(BaseModel):
    pincode: str
    message: str
    post_offices: List[PostOffice]
    total_post_offices: int


class NearbyPincodeResult(BaseModel):
    reference_pincode: str
    reference_district: str
    reference_state: str
    nearby_pincodes: List[str]
