import io
import json
import random
import string
from datetime import date, datetime, timedelta

import stripe
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Prefetch, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# Import all models correctly
from .models import Driver, DriverApplication, Rental, UserProfile, Vehicle, VehicleImage, Wallet, WalletTransaction, Review

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


# ==========================================
# GENERAL PAGES
# ==========================================

def home(request):
    pending_review = None
    
    # Check for completed trips that have NO review yet to show the popup!
    if request.user.is_authenticated:
        today = timezone.now().date()
        pending_review = Rental.objects.filter(
            user=request.user,
            end_date__lt=today,
            review__isnull=True
        ).select_related('vehicle').order_by('-end_date').first()
        
    return render(request, 'home.html', {'pending_review': pending_review})


def helpdesk(request):
    return render(request, 'helpdesk.html')


def offers(request):
    return render(request, 'offers.html')


# ==========================================
# CAPTCHA
# ==========================================

def generate_captcha_text(length=5):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choice(chars) for _ in range(length))


def captcha_image(request):
    captcha_text = generate_captcha_text()
    request.session['captcha_code'] = captcha_text

    width, height = 160, 60
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Load font (Ensure this path is correct for your OS)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 36)

    # Draw noise dots
    for _ in range(1200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(0, 0, 255))

    # Draw text with slight randomness
    for i, char in enumerate(captcha_text):
        x = 15 + i * 28 + random.randint(-3, 3)
        y = random.randint(5, 15)
        draw.text((x, y), char, font=font, fill=(0, 0, 0))

    # Apply blur
    image = image.filter(ImageFilter.GaussianBlur(0.6))

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)

    return HttpResponse(buffer, content_type="image/png")


# ==========================================
# REAL-TIME OTP API
# ==========================================

@csrf_exempt
def send_otp_api(request):
    """ Generates and sends a real OTP via Email (or SMS) """
    if request.method == "POST":
        email = request.POST.get("email")
        
        if not email:
            return JsonResponse({"status": "error", "message": "Email is required."})

        # 1. Generate 6-digit code
        otp_code = str(random.randint(100000, 999999))
        
        # 2. Save to session securely
        request.session['saved_otp'] = otp_code
        request.session['otp_email'] = email

        # 3. Send Real Email
        try:
            send_mail(
                subject='GoWheels - Your Verification Code',
                message=f'Your secure GoWheels OTP is: {otp_code}. Do not share this with anyone.',
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@gowheels.com',
                recipient_list=[email],
                fail_silently=True,
            )
            print(f"🔥 [DEVELOPER CONSOLE] OTP for {email}: {otp_code}")
            return JsonResponse({"status": "success", "message": "OTP Sent Successfully!"})
            
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request."})


# ==========================================
# AUTHENTICATION & SIGNUP
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or username}!")
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password!")

    return render(request, 'login.html')


def signup_view(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        email = request.POST.get("email")
        phone_number = request.POST.get("phone_number")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        user_otp = request.POST.get("otp_code")

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, "signup.html")

        username = email 
        if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists!")
            return render(request, "signup.html")

        saved_otp = request.session.get('saved_otp')
        saved_email = request.session.get('otp_email')

        if not saved_otp or not user_otp or saved_otp != user_otp or saved_email != email:
            messages.error(request, "Invalid or Expired OTP. Please try again.")
            return render(request, "signup.html")

        user = User.objects.create_user(
            username=username, 
            email=email, 
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        user.profile.phone_number = phone_number
        user.profile.save()

        del request.session['saved_otp']
        del request.session['otp_email']

        messages.success(request, "Engine Started! Account created successfully. Please log in.")
        return redirect("login")

    return render(request, "signup.html")


# ==========================================
# FORGOT PASSWORD FLOW
# ==========================================

def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")
        user = User.objects.filter(email=email).first()

        if user:
            otp_code = str(random.randint(100000, 999999))
            request.session['reset_otp'] = otp_code
            request.session['reset_email'] = email
            
            send_mail(
                'GoWheels - Password Reset',
                f'Your password reset code is: {otp_code}',
                'noreply@gowheels.com',
                [email],
                fail_silently=True,
            )
            print(f"🔥 [RESET OTP] for {email}: {otp_code}")
            
            messages.success(request, "If that email exists, an OTP has been sent.")
            return redirect('reset_password')
        else:
            messages.success(request, "If that email exists, an OTP has been sent.")
            return redirect('reset_password')

    return render(request, 'forgot_password.html')


def reset_password(request):
    if request.method == "POST":
        email = request.session.get('reset_email')
        otp_input = request.POST.get("otp_code")
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")
        saved_otp = request.session.get('reset_otp')

        if not email or not saved_otp:
            messages.error(request, "Session expired. Please request a new OTP.")
            return redirect('forgot_password')

        if otp_input != saved_otp:
            messages.error(request, "Invalid OTP code.")
            return redirect('reset_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('reset_password')

        user = User.objects.get(email=email)
        user.set_password(new_password)
        user.save()

        del request.session['reset_otp']
        del request.session['reset_email']

        messages.success(request, "Password successfully reset! You can now log in.")
        return redirect('login')

    return render(request, 'reset_password.html')


# ==========================================
# VEHICLES & SEARCH
# ==========================================

@login_required(login_url='login')
def list_vehicle(request):
    if request.method == "POST":
        vehicle = Vehicle.objects.create(
            owner=request.user,
            contact_number=request.POST['contact_number'],
            vehicle_name=request.POST['vehicle_name'],
            vehicle_type=request.POST['vehicle_type'],
            category=request.POST['category'],
            price_per_day=request.POST['price_per_day'],
            seats=request.POST.get('seats') or None,
            fuel_type=request.POST['fuel_type'],
            pickup_location=request.POST['pickup_location'],
        )

        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_front'], image_type='front')
        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_back'], image_type='back')
        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_inside'], image_type='inside')

        additional_images = request.FILES.getlist('additional_images')
        for img in additional_images:
            VehicleImage.objects.create(vehicle=vehicle, image=img, image_type='other')

        return redirect('vehicles')

    return render(request, 'list_vehicle.html')


def vehicles(request):
    qs = Vehicle.objects.all()

    selected_categories = [c for c in request.GET.getlist('category') if c]
    selected_vehicle_types = [vt for vt in request.GET.getlist('vehicle_type') if vt]
    selected_fuels = [f for f in request.GET.getlist('fuel_type') if f]
    status_filters = [s for s in request.GET.getlist('status') if s]

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    sort = request.GET.get('sort')
    seats = request.GET.get('seats')

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    if min_price:
        try: qs = qs.filter(price_per_day__gte=float(min_price))
        except ValueError: pass
        
    if max_price:
        try: qs = qs.filter(price_per_day__lte=float(max_price))
        except ValueError: pass

    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

            if start <= end:
                booked_ids = Rental.objects.filter(
                    start_date__lte=end,
                    end_date__gte=start
                ).values_list("vehicle_id", flat=True)
                qs = qs.exclude(id__in=booked_ids)
        except ValueError:
            messages.error(request, "Invalid date format used in filter.")

    if selected_categories and "All" not in selected_categories:
        search_cats = []
        for c in selected_categories:
            search_cats.extend([c, c.lower(), c.capitalize(), c.upper(), c.title()])
        qs = qs.filter(category__in=search_cats)

    if selected_vehicle_types:
        search_types = []
        for vt in selected_vehicle_types:
            search_types.extend([vt, vt.lower(), vt.capitalize(), vt.upper()])
        qs = qs.filter(vehicle_type__in=search_types)

    if selected_fuels:
        search_fuels = []
        for f in selected_fuels:
            search_fuels.extend([f, f.lower(), f.capitalize(), f.upper()])
        qs = qs.filter(fuel_type__in=search_fuels)

    if seats:
        try:
            seats_val = int(seats)
            if seats_val == 12:
                qs = qs.filter(seats__gte=12)
            else:
                qs = qs.filter(seats=seats_val)
        except ValueError:
            pass

    today = timezone.now().date()
    if status_filters:
        if "available" in status_filters and "soon" not in status_filters:
            qs = qs.filter(available=True).exclude(
                rental__start_date__lte=today,
                rental__end_date__gte=today
            )
        elif "soon" in status_filters and "available" not in status_filters:
            qs = qs.filter(
                available=True,
                rental__start_date__lte=today,
                rental__end_date__gte=today
            ).distinct()
        elif "available" in status_filters and "soon" in status_filters:
            qs = qs.filter(available=True)

    if sort == "price_low":
        qs = qs.order_by("price_per_day")
    elif sort == "price_high":
        qs = qs.order_by("-price_per_day")
    else:
        qs = qs.order_by("-created_at")

    for v in qs:
        v.front_image = v.images.filter(image_type="front").first()
        v.is_booked_today = v.is_booked()
        if v.is_booked_today:
            v.available_from = v.next_available_date()

    return render(request, "vehicles.html", {
        "vehicles": qs,
        "categories": Vehicle.CATEGORY_CHOICES,
        "fuel_choices": Vehicle.FUEL_CHOICES,
        "selected_categories": selected_categories,
        "selected_vehicle_types": selected_vehicle_types,
        "selected_fuels": selected_fuels,
        "selected_seats": seats, 
        "selected_statuses": status_filters, 
        "request": request,
    })


@login_required
def your_vehicles(request):
    vehicles = Vehicle.objects.filter(owner=request.user).order_by('-created_at')

    booked_count = 0
    for v in vehicles:
        v.front_image = v.images.filter(image_type="front").first()
        v.is_booked_today = v.is_booked()
        if v.is_booked_today:
            booked_count += 1

    earnings_data = Rental.objects.filter(vehicle__owner=request.user).aggregate(total=Sum('total_price'))
    total_earnings = earnings_data['total'] or 0

    return render(request, "your_vehicles.html", {
        "vehicles": vehicles,
        "booked_count": booked_count, 
        "total_earnings": total_earnings 
    })


# ==========================================
# RENTALS, BOOKINGS & REVIEWS
# ==========================================

def vehicle_booked_dates(request, vehicle_id):
    bookings = Rental.objects.filter(vehicle_id=vehicle_id).values('start_date', 'end_date')
    return JsonResponse(list(bookings), safe=False)


def is_vehicle_available(vehicle, start_date, end_date):
    return not Rental.objects.filter(
        vehicle=vehicle,
        start_date__lte=end_date,
        end_date__gte=start_date
    ).exists()


@login_required
def rent_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)
    driver_applications = DriverApplication.objects.filter(status="approved")
    user_wallet, _ = Wallet.objects.get_or_create(user=request.user)

    if request.method == "POST":
        captcha_input = request.POST.get("captcha_input", "").upper()
        captcha_code = request.session.get("captcha_code")
        if not captcha_code or captcha_input != captcha_code:
            messages.error(request, "Invalid captcha.")
            return redirect(request.path)
        del request.session['captcha_code']

        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        drive_type = request.POST.get("drive_type") or "self"
        driver_id = request.POST.get("driver_id")
        payment_mode = request.POST.get("payment_mode")
        
        full_name = request.POST.get("full_name")
        age = request.POST.get("age")
        phone_number = request.POST.get("phone_number")
        aadhaar_image = request.FILES.get("aadhaar_image")
        license_image = request.FILES.get("license_image")

        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Invalid dates.")
            return redirect(request.path)
        
        if not is_vehicle_available(vehicle, start, end):
            messages.error(request, "Vehicle unavailable for these dates.")
            return redirect(request.path)

        days = (end - start).days + 1
        total_price = days * vehicle.price_per_day
        selected_driver = None

        if drive_type == "driver" and driver_id:
            selected_driver = Driver.objects.get(id=int(driver_id))
            total_price += days * selected_driver.price_per_day

        # PAYMENT LOGIC
        if payment_mode == 'wallet':
            if user_wallet.balance >= total_price:
                user_wallet.balance -= total_price
                user_wallet.save()
                WalletTransaction.objects.create(
                    wallet=user_wallet, amount=total_price, transaction_type='DEBIT',
                    description=f"Rental: {vehicle.vehicle_name}", status='SUCCESS'
                )
                Rental.objects.create(
                    user=request.user, vehicle=vehicle, driver=selected_driver,
                    start_date=start, end_date=end, total_price=total_price,
                    full_name=full_name, age=age, phone_number=phone_number,
                    drive_type=drive_type, payment_mode='wallet',
                    aadhaar_image=aadhaar_image, license_image=license_image
                )
                messages.success(request, f"Booking Successful! ₹{total_price} paid via Wallet.")
                return redirect("rent_history")
            else:
                messages.error(request, f"Insufficient Wallet Balance (Required: ₹{total_price})")
                return redirect(request.path)

        elif payment_mode == 'online':
            request.session['booking_data'] = {
                'vehicle_id': vehicle.id, 'start_date': start_date, 'end_date': end_date,
                'total_price': float(total_price), 'full_name': full_name, 'age': age,
                'phone_number': phone_number, 'drive_type': drive_type, 'driver_id': driver_id,
                'payment_mode': 'online'
            }
            domain_url = 'http://127.0.0.1:8000/'
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': { 'currency': 'inr', 'product_data': {'name': f"Rent {vehicle.vehicle_name}"}, 'unit_amount': int(total_price * 100) },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=domain_url + 'rent/success/', cancel_url=domain_url + f'rent/{vehicle.id}/',
            )
            return redirect(checkout_session.url, code=303)

        else:
            Rental.objects.create(
                user=request.user, vehicle=vehicle, driver=selected_driver,
                start_date=start, end_date=end, total_price=total_price,
                full_name=full_name, age=age, phone_number=phone_number,
                drive_type=drive_type, payment_mode='cash',
                aadhaar_image=aadhaar_image, license_image=license_image
            )
            messages.success(request, "Booking Confirmed! Please pay cash on pickup.")
            return redirect("rent_history")

    return render(request, "rent_vehicle.html", {
        "vehicle": vehicle, "driver_applications": driver_applications, "wallet_balance": user_wallet.balance,
    })


def finalize_booking(request):
    data = request.session.get('booking_data')
    if not data: return redirect('home')

    vehicle = Vehicle.objects.get(id=data['vehicle_id'])
    selected_driver = Driver.objects.get(id=int(data['driver_id'])) if data.get('driver_id') else None

    Rental.objects.create(
        user=request.user, vehicle=vehicle, driver=selected_driver,
        start_date=data['start_date'], end_date=data['end_date'],
        total_price=data['total_price'], full_name=data['full_name'],
        age=data['age'], phone_number=data['phone_number'],
        drive_type=data['drive_type'], payment_mode=data['payment_mode'],
    )
    del request.session['booking_data']
    messages.success(request, "Booking Confirmed Successfully!")
    return redirect("rent_history")


@login_required
def rent_success_callback(request):
    return finalize_booking(request)


@login_required
def submit_review(request):
    if request.method == "POST":
        rental_id = request.POST.get('rental_id')
        rental = get_object_or_404(Rental, id=rental_id, user=request.user)
        
        if not hasattr(rental, 'review') and rental.end_date < timezone.now().date():
            driver_rating = request.POST.get('driver_rating')
            driver_rating_val = int(driver_rating) if driver_rating else None

            Review.objects.create(
                rental=rental,
                vehicle=rental.vehicle,
                driver=rental.driver,
                user=request.user,
                cleanliness=int(request.POST.get('cleanliness', 5)),
                performance=int(request.POST.get('performance', 5)),
                comfort=int(request.POST.get('comfort', 5)),
                driver_rating=driver_rating_val,
                comment=request.POST.get('comment', '')
            )
            
            if rental.driver and driver_rating_val:
                rental.driver.update_rating()
                
            messages.success(request, "Review submitted! Thank you for your feedback.")
        
    return redirect('rent_history')


# ==========================================
# DASHBOARD / USER GRAPHICS
# ==========================================

@login_required
def auto_fix_graph(request):
    user = request.user
    vehicle = Vehicle.objects.first()
    if not vehicle:
        vehicle = Vehicle.objects.create(
            owner=user, vehicle_name="Test Graph Car", contact_number="0000000000",
            vehicle_type="car", category="Sedan", price_per_day=1000,
            fuel_type="Petrol", pickup_location="Test City"
        )

    dates = [ date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 20), date(2026, 1, 28), date(2026, 2, 5) ]
    existing_rentals = list(Rental.objects.filter(user=user))
    
    for i, start_dt in enumerate(dates):
        end_dt = start_dt + timedelta(days=2)
        price = 2000
        
        if i < len(existing_rentals):
            rental = existing_rentals[i]
            rental.start_date = start_dt
            rental.end_date = end_dt
            rental.total_price = price
            rental.save()
        else:
            ref_rental = existing_rentals[0] if existing_rentals else None
            Rental.objects.create(
                user=user, vehicle=vehicle, start_date=start_dt, end_date=end_dt, total_price=price,
                full_name=user.get_full_name() or user.username, age=25, phone_number="9999999999",
                drive_type="self", payment_mode="online",
                aadhaar_image=ref_rental.aadhaar_image if ref_rental else "defaults/doc.jpg",
                license_image=ref_rental.license_image if ref_rental else "defaults/doc.jpg"
            )

    messages.success(request, "Graph Data Fixed! Added 5 weekly data points.")
    return redirect('rent_history')


@login_required
def rent_history(request):
    today = timezone.now().date()
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'all')
    sort_by = request.GET.get('sort', '-rented_at')

    allowed_sorts = ['rented_at', '-rented_at', 'total_price', '-total_price']
    if sort_by not in allowed_sorts: sort_by = '-rented_at'

    rentals_qs = Rental.objects.filter(user=request.user).select_related('vehicle', 'driver', 'review').prefetch_related(
        Prefetch('vehicle__images', queryset=VehicleImage.objects.filter(image_type='front'), to_attr='front_images')
    )

    if search_query: rentals_qs = rentals_qs.filter(vehicle__vehicle_name__icontains=search_query)

    if status_filter == "active": rentals_qs = rentals_qs.filter(start_date__lte=today, end_date__gte=today)
    elif status_filter == "upcoming": rentals_qs = rentals_qs.filter(start_date__gt=today)
    elif status_filter == "completed": rentals_qs = rentals_qs.filter(end_date__lt=today)

    rentals_qs = rentals_qs.annotate(duration=ExpressionWrapper(F('end_date') - F('start_date'), output_field=DurationField()))

    timeline_qs = rentals_qs.annotate(week=TruncWeek('start_date')).values('week').annotate(total=Sum('total_price')).order_by('week')
    time_labels = [t['week'].strftime("%d %b") for t in timeline_qs]
    time_values = [t['total'] for t in timeline_qs]

    stats = rentals_qs.aggregate(total_trips=Count('id'), total_cash=Sum('total_price'), max_days=Max('duration'))
    total_spend = stats['total_cash'] or 0
    stats['max_days'] = stats['max_days'].days if stats['max_days'] else 0

    favourite_vehicle = rentals_qs.values('vehicle__vehicle_name').annotate(count=Count('id')).order_by('-count').first()
    favourite_vehicle_name = favourite_vehicle['vehicle__vehicle_name'] if favourite_vehicle else "N/A"
    favourite_vehicle_count = favourite_vehicle['count'] if favourite_vehicle else 0

    if total_spend >= 30000: tier = "Elite"; remaining = 0; progress_percent = 100
    elif total_spend >= 15000: tier = "Platinum"; remaining = 30000 - total_spend; progress_percent = int((total_spend / 30000) * 100)
    elif total_spend >= 5000: tier = "Gold"; remaining = 15000 - total_spend; progress_percent = int((total_spend / 15000) * 100)
    else: tier = "Silver"; remaining = 5000 - total_spend; progress_percent = int((total_spend / 5000) * 100)

    cat_data = rentals_qs.values('vehicle__category').annotate(total=Sum('total_price'))
    cat_labels = [c['vehicle__category'] for c in cat_data]
    cat_values = [c['total'] for c in cat_data]

    rentals = []
    for r in rentals_qs.order_by(sort_by):
        r.invoice_no = f"INV-{r.rented_at.year}-{r.id:05d}"
        if r.start_date <= today <= r.end_date: r.status_label = "Active"
        elif r.start_date > today: r.status_label = "Upcoming"
        else: r.status_label = "Completed"
        
        r.vehicle.front_image = r.vehicle.front_images[0] if hasattr(r.vehicle, 'front_images') and r.vehicle.front_images else None
        
        # Calculate Detailed Bill
        days = (r.end_date - r.start_date).days + 1
        r.days_count = days
        r.vehicle_fare = r.vehicle.price_per_day * days
        r.driver_fare = r.driver.price_per_day * days if r.drive_type == 'driver' and r.driver else 0
        
        rentals.append(r)

    return render(request, "rent_history.html", {
        "rentals": rentals, "stats": stats, "favourite_vehicle_name": favourite_vehicle_name,
        "favourite_vehicle_count": favourite_vehicle_count, "tier": tier, "progress_percent": progress_percent,
        "remaining": remaining, "cat_labels": json.dumps(cat_labels), "cat_values": json.dumps(cat_values),
        "time_labels": json.dumps(time_labels), "time_values": json.dumps(time_values), "status_filter": status_filter,
    })


# ==========================================
# DRIVERS
# ==========================================

@login_required
def become_driver(request):
    application = DriverApplication.objects.filter(user=request.user).first()
    
    if request.method == "POST":
        full_name = request.POST.get("full_name")
        age = request.POST.get("age")
        phone_number = request.POST.get("phone_number")
        experience_years = request.POST.get("experience_years")
        price_per_day = request.POST.get("price_per_day")
        aadhaar_image = request.FILES.get("aadhaar_image")
        license_image = request.FILES.get("license_image")
        profile_photo = request.FILES.get("profile_photo")

        if application and application.status == 'rejected':
            application.full_name = full_name
            application.age = age
            application.phone_number = phone_number
            application.experience_years = experience_years
            application.price_per_day = price_per_day
            if aadhaar_image: application.aadhaar_image = aadhaar_image
            if license_image: application.license_image = license_image
            if profile_photo: application.profile_photo = profile_photo
            application.status = 'pending'
            application.save()
        elif not application:
            DriverApplication.objects.create(
                user=request.user, full_name=full_name, age=age, phone_number=phone_number,
                experience_years=experience_years, price_per_day=price_per_day,
                aadhaar_image=aadhaar_image, license_image=license_image,
                profile_photo=profile_photo, status='pending'
            )

        messages.success(request, "Your application has been submitted! It is now under review.")
        return redirect("become_driver")

    context = {'status': 'new'}
    if application:
        context['status'] = application.status
        if application.status == 'approved':
            driver = Driver.objects.filter(application=application).first()
            if driver:
                total_earned = Rental.objects.filter(driver=driver).aggregate(Sum('total_price'))['total_price__sum'] or 0
                trips_completed = Rental.objects.filter(driver=driver, end_date__lt=date.today()).count()
                context['driver'] = driver
                context['total_earned'] = total_earned
                context['trips_completed'] = trips_completed
            else:
                context['status'] = 'pending'

    return render(request, "become_driver.html", context)


# ==========================================
# WALLET & PAYMENTS
# ==========================================

@login_required
def payments_view(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')
    return render(request, 'payments.html', {'wallet': wallet, 'transactions': transactions, 'total_spent': wallet.balance})


@login_required
def create_checkout_session(request):
    if request.method == 'POST':
        try:
            amount_str = request.POST.get('amount', '500')
            amount_inr = int(amount_str)
            amount_paise = amount_inr * 100 
            request.session['recharge_amount'] = amount_inr
            domain_url = 'http://127.0.0.1:8000/'
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': { 'currency': 'inr', 'product_data': { 'name': 'Wallet Recharge', 'description': f"Add ₹{amount_inr} to GoWheels Wallet" }, 'unit_amount': amount_paise },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=domain_url + 'payment/success_handler/',
                cancel_url=domain_url + 'payments/',
            )
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('payments')
    return redirect('payments')


@login_required
def payment_success_handler(request):
    amount = request.session.get('recharge_amount')
    if amount:
        wallet = request.user.wallet
        wallet.balance += amount
        wallet.save()
        WalletTransaction.objects.create(wallet=wallet, amount=amount, transaction_type='CREDIT', description='Wallet Recharge via Stripe')
        del request.session['recharge_amount']
        
        return render(request, 'payments.html', {
            'payment_status': 'success', 'message': f'₹{amount} has been added to your wallet successfully!',
            'wallet': wallet, 'transactions': WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')
        })
    return redirect('payments')


def payment_success(request):
    return render(request, 'payments.html')


def payment_cancel(request):
    return render(request, 'home.html', {'message': 'Payment Cancelled'})


@login_required
def edit_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)

    if request.method == "POST":
        vehicle.contact_number = request.POST.get('contact_number')
        vehicle.vehicle_name = request.POST.get('vehicle_name')
        vehicle.vehicle_type = request.POST.get('vehicle_type')
        vehicle.category = request.POST.get('category')
        vehicle.price_per_day = request.POST.get('price_per_day')
        vehicle.seats = request.POST.get('seats')
        vehicle.fuel_type = request.POST.get('fuel_type')
        vehicle.pickup_location = request.POST.get('pickup_location')
        vehicle.save()
        messages.success(request, f"'{vehicle.vehicle_name}' has been updated successfully!")
        return redirect('your_vehicles')

    return render(request, 'edit_vehicle.html', {'vehicle': vehicle})


@login_required
@require_POST
def toggle_vehicle_status(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)
    try:
        data = json.loads(request.body)
        vehicle.available = data.get('available', True)
        vehicle.save()
        return JsonResponse({'success': True, 'is_available': vehicle.available})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)