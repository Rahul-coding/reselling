"""Streamlit marketplace app — create account, upload product photos, browse listings."""
import os
import uuid

import streamlit as st
from PIL import Image

from db import (
    UPLOAD_DIR,
    count_requests_for_seller,
    create_listing,
    create_purchase_request,
    create_user,
    delete_listing,
    get_all_listings,
    get_images_for_listing,
    get_listing_by_id,
    get_listing_owner,
    get_listings_for_user,
    get_requests_for_seller,
    get_user_by_id,
    init_db,
    verify_user,
)

os.makedirs(UPLOAD_DIR, exist_ok=True)

init_db()

MAX_IMAGE_SIZE = (800, 800)
MAX_IMAGES_PER_LISTING = 5


# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #
def login(user_id: int) -> None:
    st.session_state["user_id"] = user_id


def logout() -> None:
    st.session_state.pop("user_id", None)


# --------------------------------------------------------------------------- #
# UI components
# --------------------------------------------------------------------------- #
def show_auth() -> None:
    st.title("📦 Reselling Marketplace")
    st.caption("Create an account or log in to list products — like Craigslist / Facebook Marketplace.")

    # --- Persistent confirmation banner (survives st.rerun) ---
    if "auth_success" in st.session_state:
        msg = st.session_state.pop("auth_success")
        st.success(msg, icon="✅")

    # Default auth mode can be set programatically after account creation.
    default_mode = st.session_state.get("auth_mode", "Login")
    mode = st.sidebar.radio("Auth", ["Login", "Create Account"], index=["Login", "Create Account"].index(default_mode))
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Submit"):
        if not username or not password:
            st.warning("Please enter both username and password.")
            return

        if mode == "Create Account":
            uid = create_user(username, password)
            if uid:
                # Store confirmation and auto-switch to login mode so the
                # user can immediately sign in with the newly created account.
                st.session_state["auth_success"] = f"✅ Account **{username}** created successfully! You can now log in below."
                st.session_state["auth_mode"] = "Login"
                st.rerun()
            else:
                st.error("❌ Username already taken. Try another one.")
        else:
            uid = verify_user(username, password)
            if uid:
                login(uid)
                st.session_state.pop("auth_mode", None)
                st.rerun()
            else:
                st.error("❌ Invalid credentials. Check your username/password.")


def save_uploaded_images(uploaded_files) -> list[str]:
    """Persist uploaded or camera-captured images to UPLOAD_DIR.

    Both ``st.file_uploader`` and ``st.camera_input`` return file-like
    objects, so they're handled identically here.
    """
    saved: list[str] = []
    for uf in uploaded_files:
        if uf is None:
            continue
        img = Image.open(uf)
        img.thumbnail(MAX_IMAGE_SIZE)
        ext = os.path.splitext(uf.name)[1].lower()
        # st.camera_input returns a BytesIO with no extension;
        # it always produces PNG data, so default to ".png" in that case.
        if not ext:
            ext = ".png"
        filename = f"{uuid.uuid4().hex}{ext}"
        img.save(os.path.join(UPLOAD_DIR, filename))
        saved.append(filename)
        return saved


def show_upload_listing() -> None:
    # --- Persistent confirmation banner (survives st.rerun) ---
    if "listing_success" in st.session_state:
        listing_id, listing_title = st.session_state.pop("listing_success")
        st.success(
            f"✅ Listing **#{listing_id} — {listing_title}** created successfully! "
            f"It's now visible in your Dashboard and the Marketplace.",
            icon="✅",
        )

    st.title("📤 Upload a Listing")

    title = st.text_input("Title", placeholder="e.g. iPhone 12 Pro")
    description = st.text_area("Description", placeholder="Condition, details, etc.")
    price = st.number_input("Price ($)", min_value=0.0, format="%.2f")

    # --- Photo input ---
    # Camera input must live *outside* a form so that it renders and can be
    # used immediately when the user selects "Take a picture" — it doesn't
    # need to wait for a form submit, and it returns a snapshot right away.
    source = st.radio(
        "Add photos from:",
        ["📁 Choose files", "📷 Take a picture"],
        horizontal=True,
        index=0,
        key="photo_source",
    )

    uploaded: list = []
    camera_img = None

    if source == "📁 Choose files":
        uploaded = st.file_uploader(
            "Photos",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="file_uploader",
        ) or []
    else:  # "📷 Take a picture"
        camera_img = st.camera_input("Take a picture", key="camera")
        if camera_img is not None:
            st.image(camera_img, caption="📸 Preview", width="stretch")

    submitted = st.button("List Item", type="primary")

    if submitted:
        # Combine selected files and the camera snapshot into one list.
        all_images: list = []
        if uploaded:
            all_images.extend([f for f in uploaded if f is not None])
        if camera_img is not None:
            all_images.append(camera_img)

        if not title or not all_images:
            st.warning("Title and at least one photo are required.")
            return
        if len(all_images) > MAX_IMAGES_PER_LISTING:
            st.warning(f"Maximum {MAX_IMAGES_PER_LISTING} photos allowed.")
            return
        filenames = save_uploaded_images(all_images)
        listing_id = create_listing(st.session_state["user_id"], title, description, price, filenames)
        # Store confirmation in session state so it persists across the rerun
        # and shows a prominent banner at the top of the page.
        st.session_state["listing_success"] = (listing_id, title)
        st.rerun()


def show_my_listings() -> None:
    st.title("📋 My Listings")
    user = get_user_by_id(st.session_state["user_id"])
    st.caption(f"Logged in as **{user['username']}**")

    listings = get_listings_for_user(st.session_state["user_id"])
    if not listings:
        st.info("You haven't listed anything yet. Go to **Upload** to get started.")
        return

    # Show number of purchase requests received for this seller's listings.
    n_requests = count_requests_for_seller(st.session_state["user_id"])
    if n_requests:
        st.info(f"📬 You have **{n_requests}** purchase request(s). Check the **Messages** tab!")

    for listing in listings:
        _render_listing_card(listing, show_delete=True)


def show_marketplace() -> None:
    st.title("🛒 Marketplace")
    st.caption("Browse items from other sellers.")

    # If a buyer clicked "Request to Buy", show the inline request form.
    request_listing_id = st.session_state.get("request_listing_id")
    if request_listing_id:
        show_purchase_request_form(request_listing_id)
        st.markdown("---")

    listings = [l for l in get_all_listings() if l["user_id"] != st.session_state["user_id"]]
    if not listings:
        st.info("No items from other sellers yet. Be the first to upload!")
        return
    for listing in listings:
        _render_listing_card(listing, show_delete=False, show_request=True)


def _render_listing_card(listing, show_delete: bool, show_request: bool = False) -> None:
    detail_col_ratio = [1, 3, 1] if (show_delete or show_request) else [1, 4]
    cols = st.columns(detail_col_ratio)
    with cols[0]:
        imgs = get_images_for_listing(listing["id"])
        if imgs:
            st.image(os.path.join(UPLOAD_DIR, imgs[0]), width="stretch")
    with cols[1]:
        st.subheader(listing["title"])
        st.markdown(f"**${listing['price']:,.2f}**")
        if listing["description"]:
            st.write(listing["description"])
        st.caption(f"Listed {listing['created_at'][:10]}")
    with cols[2]:
        if show_delete:
            if st.button("🗑️", key=f"del_{listing['id']}"):
                delete_listing(listing["id"])
                st.rerun()
        if show_request:
            if st.button("💌 Request to Buy", key=f"req_{listing['id']}"):
                st.session_state["request_listing_id"] = listing["id"]
                st.rerun()
    st.divider()


def show_purchase_request_form(listing_id: int) -> None:
    """Inline form shown when a buyer clicks 'Request to Buy'."""
    listing = get_listing_by_id(listing_id)
    if listing is None:
        st.error("This listing is no longer available.")
        return

    seller = get_user_by_id(listing["user_id"])
    with st.expander(f"💌 Send a purchase request to {seller['username']} for \"{listing['title']}\"", expanded=True):
        buyer_email = st.text_input("Your email", placeholder="you@example.com")
        message = st.text_area("Message (optional)", placeholder="Hi, is this still available? Want to pick up today.")
        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("Send Request", type="primary", key=f"send_req_{listing_id}"):
                if not buyer_email or "@" not in buyer_email:
                    st.warning("Please enter a valid email address.")
                    return
                create_purchase_request(
                    listing_id=listing_id,
                    buyer_id=st.session_state.get("user_id"),
                    buyer_email=buyer_email,
                    message=message,
                )
                st.session_state["request_success"] = (listing_id, listing["title"])
                st.session_state.pop("request_listing_id", None)
                st.rerun()
        with col_b:
            if st.button("Cancel", key=f"cancel_req_{listing_id}"):
                st.session_state.pop("request_listing_id", None)
                st.rerun()


def show_purchase_requests() -> None:
    """Seller-facing view: list all purchase requests received for the seller's listings."""
    st.title("💌 Purchase Requests")
    user = get_user_by_id(st.session_state["user_id"])
    st.caption(f"Messages for **{user['username']}**")

    # --- Persistent confirmation banner ---
    if "request_success" in st.session_state:
        req_id, req_title = st.session_state.pop("request_success")
        st.success(
            f"✅ Your purchase request for **{req_title}** has been sent to the seller!",
            icon="✅",
        )

    requests = get_requests_for_seller(st.session_state["user_id"])
    if not requests:
        st.info("You haven't received any purchase requests yet. List items to get starts!")
        return

    st.markdown(f"**You have {len(requests)} purchase request(s):**")
    for req in requests:
        with st.container():
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(f"**Re: {req['listing_title']}**")
                st.markdown(f"📧 **{req['buyer_email']}**")
                if req["message"]:
                    st.write(req["message"])
                st.caption(f"Received {req['created_at'][:16].replace('T', ' ')}")
            with cols[1]:
                # In a real app this could trigger an email/SMS; here we show a hint.
                if st.button("Copy email", key=f"copy_{req['id']}"):
                    st.info(f"Seller contact: {req['buyer_email']}")
            st.divider()


# --------------------------------------------------------------------------- #
# Main router
# --------------------------------------------------------------------------- #
def main() -> None:
    if "user_id" not in st.session_state:
        show_auth()
        return

    st.sidebar.title("🧭 Navigation")
    # Show a badge with the number of purchase requests in the sidebar.
    n_requests = count_requests_for_seller(st.session_state["user_id"])
    msg_label = "Messages"
    if n_requests:
        msg_label = f"Messages ({n_requests})"
    pages = ["Dashboard", "Upload", "Marketplace", msg_label]
    page = st.sidebar.radio("Go to", pages, index=0)
    st.sidebar.divider()
    if st.sidebar.button("Logout"):
        logout()
        st.rerun()

    if page.startswith("Messages"):
        show_purchase_requests()
    elif page == "Dashboard":
        show_my_listings()
    elif page == "Upload":
        show_upload_listing()
    elif page == "Marketplace":
        show_marketplace()


if __name__ == "__main__":
    main()
