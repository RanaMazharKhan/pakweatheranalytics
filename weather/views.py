from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q
import pandas as pd
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from .models import WeatherData
from .forms import WeatherDataForm, CSVUploadForm, SearchFilterForm
from .utils import get_filtered_data, calculate_statistics, generate_insights, get_chart_data
from .tasks import send_daily_reports
from .services import ensure_weather_data, ensure_weather_data_async


def is_admin(user):
    return user.is_staff or user.is_superuser


def home_view(request):
    if request.user.is_authenticated:
        return redirect('weather:dashboard')
    try:
        ensure_weather_data_async()
    except Exception as e:
        logger.exception("Failed to sync weather data in home_view")
    total_records = WeatherData.objects.count()
    cities_count = WeatherData.objects.values('city').distinct().count()
    latest_data = WeatherData.objects.order_by('-date')[:5]
    return render(request, 'weather/home.html', {'total_records': total_records, 'cities_count': cities_count, 'latest_data': latest_data})


@login_required
def dashboard_view(request):
    try:
        ensure_weather_data_async()
    except Exception as e:
        logger.exception("Failed to sync weather data in dashboard_view")
        messages.warning(request, "Failed to sync historical weather data. You can still use the live dashboard!")
    form = SearchFilterForm(request.GET or None)
    city = request.GET.get('city')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    
    queryset = get_filtered_data(city=city, date_from=date_from, date_to=date_to, temp_min=float(temp_min) if temp_min else None, temp_max=float(temp_max) if temp_max else None)
    stats = calculate_statistics(queryset)
    line_chart_data = get_chart_data(queryset, 'line')
    bar_chart_data = get_chart_data(queryset, 'bar')
    pie_chart_data = get_chart_data(queryset, 'pie')
    
    preferred_cities = []
    if hasattr(request.user, 'profile'):
        preferred_cities = request.user.profile.get_preferred_cities_list()
    if not preferred_cities:
        preferred_cities = ['Lahore', 'Karachi', 'Islamabad']

    return render(request, 'weather/dashboard.html', {
        'form': form, 'stats': stats,
        'line_chart_data': json.dumps(line_chart_data) if line_chart_data else None,
        'bar_chart_data': json.dumps(bar_chart_data) if bar_chart_data else None,
        'pie_chart_data': json.dumps(pie_chart_data) if pie_chart_data else None,
        'preferred_cities': json.dumps(preferred_cities),
    })


@login_required
def search_view(request):
    try:
        ensure_weather_data_async()
    except Exception as e:
        logger.exception("Failed to sync weather data in search_view")
    form = SearchFilterForm(request.GET or None)
    city = request.GET.get('city')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    sort_by = request.GET.get('sort_by', '-date')
    
    queryset = get_filtered_data(city=city, date_from=date_from, date_to=date_to, temp_min=float(temp_min) if temp_min else None, temp_max=float(temp_max) if temp_max else None, sort_by=sort_by)
    
    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    return render(request, 'weather/search.html', {'form': form, 'page_obj': page_obj, 'total_results': queryset.count()})


@login_required
def visualizations_view(request):
    try:
        ensure_weather_data_async()
    except Exception as e:
        logger.exception("Failed to sync weather data in visualizations_view")
    form = SearchFilterForm(request.GET or None)
    city = request.GET.get('city')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    
    queryset = get_filtered_data(city=city, date_from=date_from, date_to=date_to, temp_min=float(temp_min) if temp_min else None, temp_max=float(temp_max) if temp_max else None)
    
    return render(request, 'weather/visualizations.html', {
        'form': form,
        'line_chart_data': json.dumps(get_chart_data(queryset, 'line')),
        'bar_chart_data': json.dumps(get_chart_data(queryset, 'bar')),
        'pie_chart_data': json.dumps(get_chart_data(queryset, 'pie')),
        'histogram_data': json.dumps(get_chart_data(queryset, 'histogram')),
        'scatter_data': json.dumps(get_chart_data(queryset, 'scatter')),
    })


@login_required
def insights_view(request):
    try:
        ensure_weather_data_async()
    except Exception as e:
        logger.exception("Failed to sync weather data in insights_view")
    form = SearchFilterForm(request.GET or None)
    city = request.GET.get('city')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    
    queryset = get_filtered_data(city=city, date_from=date_from, date_to=date_to, temp_min=float(temp_min) if temp_min else None, temp_max=float(temp_max) if temp_max else None)
    
    return render(request, 'weather/insights.html', {'form': form, 'insights': generate_insights(queryset), 'stats': calculate_statistics(queryset)})


@login_required
def reports_view(request):
    export_format = request.GET.get('format', 'csv')
    city = request.GET.get('city')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    sort_by = request.GET.get('sort_by', '-date')
    
    queryset = get_filtered_data(city=city, date_from=date_from, date_to=date_to, temp_min=float(temp_min) if temp_min else None, temp_max=float(temp_max) if temp_max else None, sort_by=sort_by)
    df = WeatherData.get_dataframe(queryset)
    
    if df.empty:
        messages.warning(request, 'No data available to export.')
        return redirect('weather:search')
    
    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="weather_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        df.to_csv(response, index=False)
        return response
    
    elif export_format == 'pdf':
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="weather_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        doc = SimpleDocTemplate(response, pagesize=landscape(A4))
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph("Weather Analytics Report", ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, alignment=1)))
        elements.append(Spacer(1, 20))
        
        table_data = [['Date', 'City', 'Max Temp', 'Min Temp', 'Avg Temp', 'Humidity', 'Precipitation', 'Wind Speed', 'Condition']]
        for _, row in df.iterrows():
            table_data.append([row['date'].strftime('%Y-%m-%d'), row['city'], f"{row['temperature_max']}C", f"{row['temperature_min']}C", f"{row['temperature_avg']}C", f"{row['humidity']}%", f"{row['precipitation']}mm", f"{row['wind_speed']}km/h", row['weather_condition']])
        
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2a6c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
        doc.build(elements)
        return response
    
    return redirect('weather:search')


@login_required
@user_passes_test(is_admin)
def upload_data_view(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                df = pd.read_csv(form.cleaned_data['csv_file'])
                df.columns = df.columns.str.lower().str.strip()
                df['date'] = pd.to_datetime(df['date']).dt.date
                df['wind_direction'] = df.get('wind_direction', 'N')
                df['pressure'] = df.get('pressure', 1013.25)
                df['visibility'] = df.get('visibility', 10)
                df['weather_condition'] = df.get('weather_condition', 'Clear')
                count = WeatherData.import_from_dataframe(df)
                messages.success(request, f'Successfully imported {count} records.')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
            return redirect('weather:upload_data')
    else:
        form = CSVUploadForm()
    return render(request, 'weather/upload_data.html', {'form': form, 'total_records': WeatherData.objects.count()})


@login_required
@user_passes_test(is_admin)
def data_list_view(request):
    queryset = WeatherData.objects.all().order_by('-date', 'city')
    search_query = request.GET.get('q')
    if search_query:
        queryset = queryset.filter(Q(city__icontains=search_query) | Q(weather_condition__icontains=search_query))
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'weather/data_list.html', {'page_obj': page_obj, 'search_query': search_query})


@login_required
@user_passes_test(is_admin)
def create_record_view(request):
    if request.method == 'POST':
        form = WeatherDataForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Record created.')
            return redirect('weather:data_list')
    else:
        form = WeatherDataForm()
    return render(request, 'weather/edit_record.html', {'form': form, 'title': 'Create Record'})


@login_required
@user_passes_test(is_admin)
def update_record_view(request, pk):
    record = get_object_or_404(WeatherData, pk=pk)
    if request.method == 'POST':
        form = WeatherDataForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, 'Record updated.')
            return redirect('weather:data_list')
    else:
        form = WeatherDataForm(instance=record)
    return render(request, 'weather/edit_record.html', {'form': form, 'title': 'Update Record'})


@login_required
@user_passes_test(is_admin)
def delete_record_view(request, pk):
    record = get_object_or_404(WeatherData, pk=pk)
    if request.method == 'POST':
        record.delete()
        messages.success(request, 'Record deleted.')
        return redirect('weather:data_list')
    return render(request, 'weather/edit_record.html', {'record': record, 'title': 'Delete Record'})


@login_required
@user_passes_test(is_admin)
def refresh_weather_data_view(request):
    result = ensure_weather_data(force=True)
    if result and result['saved']:
        messages.success(request, f'Weather data refreshed: {result["saved"]} records updated from Open-Meteo.')
    elif result and result['errors']:
        messages.warning(request, f'Partial refresh: {result["saved"]} records saved. Some cities failed.')
    else:
        messages.info(request, 'Weather data is already up to date.')
    return redirect(request.GET.get('next', 'weather:dashboard'))


@login_required
@user_passes_test(is_admin)
def send_reports_now_view(request):
    sent, failed, skipped = send_daily_reports()
    messages.success(
        request,
        f'Daily reports: {sent} sent, {failed} failed, {skipped} already sent today.',
    )
    return redirect('weather:dashboard')


def sitemap_view(request):
    domain = request.build_absolute_uri('/').rstrip('/')
    if not domain.startswith('https://') and not request.is_secure() and 'localhost' not in domain and '127.0.0.1' not in domain:
        domain = domain.replace('http://', 'https://')
    return render(request, 'sitemap.xml', {'domain': domain}, content_type='application/xml')


def robots_txt_view(request):
    domain = request.build_absolute_uri('/').rstrip('/')
    if not domain.startswith('https://') and not request.is_secure() and 'localhost' not in domain and '127.0.0.1' not in domain:
        domain = domain.replace('http://', 'https://')
    return render(request, 'robots.txt', {'domain': domain}, content_type='text/plain')
