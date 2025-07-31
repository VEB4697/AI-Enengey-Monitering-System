from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser # Import your custom user model

class CustomUserCreationForm(UserCreationForm):
    # Add the extra fields you want in the registration form
    first_name = forms.CharField(max_length=30, required=False, help_text='Optional.')
    last_name = forms.CharField(max_length=150, required=False, help_text='Optional.')
    email = forms.EmailField(required=True, help_text='Required. Enter a valid email address.')
    phone_number = forms.CharField(max_length=15, required=False, help_text='Optional. e.g., +919876543210')
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    gender = forms.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_picture = forms.ImageField(required=False)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        # Explicitly list all fields, including those inherited from UserCreationForm.Meta.fields
        # This ensures Django correctly maps 'password' and 'password2'
        fields = (
            'username', # Inherited from UserCreationForm
            'password', # Inherited from UserCreationForm
            'password2', # Inherited from UserCreationForm
            'first_name',
            'last_name',
            'email',
            'phone_number',
            'date_of_birth',
            'gender',
            'address',
            'profile_picture'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure email is required.
        self.fields['email'].required = True
        # UserCreationForm already ensures 'password' and 'password2' are required.
        # No need to explicitly set them here.

