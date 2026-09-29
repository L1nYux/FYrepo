from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import FinanceEntry, Submission, Task, validate_private_file


class RegisterForm(UserCreationForm):
    invite_code = forms.CharField(label='邀请码', max_length=100, strip=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)
        labels = {'username': '账户名'}

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('账户名已被使用。')
        return username


class ProgressForm(forms.Form):
    progress = forms.IntegerField(label='完成进度（0-99）', min_value=0, max_value=99)


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ('title', 'description', 'assignee', 'due_date')
        widgets = {'description': forms.Textarea(attrs={'rows': 5}), 'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = User.objects.filter(is_active=True, is_staff=False).order_by('username')


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ('note', 'attachment')
        labels = {'note': '成果说明', 'attachment': '成果文件'}
        widgets = {'note': forms.Textarea(attrs={'rows': 4}),
                   'attachment': forms.FileInput(attrs={'accept': '.txt,.pdf,.doc,.docx,.xls,.xlsx'})}

    def clean_attachment(self):
        value = self.cleaned_data['attachment']
        validate_private_file(value)
        return value


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='审核决定', choices=[('accept', '通过结项'), ('reject', '退回修改')])
    note = forms.CharField(label='审核意见', max_length=3000, required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        data = super().clean()
        if data.get('decision') == 'reject' and not data.get('note', '').strip():
            self.add_error('note', '退回时请填写原因。')
        return data


class FinanceForm(forms.ModelForm):
    class Meta:
        model = FinanceEntry
        fields = ('kind', 'amount', 'occurred_on', 'memo', 'receipt')
        labels = {'kind': '类型', 'amount': '金额（元）', 'occurred_on': '发生日期', 'memo': '说明', 'receipt': '发票或证明文件'}
        widgets = {'occurred_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'memo': forms.Textarea(attrs={'rows': 4}),
                   'receipt': forms.FileInput(attrs={'accept': '.txt,.pdf,.doc,.docx,.xls,.xlsx'})}

    def clean_receipt(self):
        value = self.cleaned_data.get('receipt')
        if value and not isinstance(value, str) and hasattr(value, 'size'):
            validate_private_file(value)
        return value
